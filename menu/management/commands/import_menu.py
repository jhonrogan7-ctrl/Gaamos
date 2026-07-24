import json
import urllib.request
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from PIL import Image

from menu import publish
from menu.models import Company, Branch
from menu.tenancy import set_current_company, reset_current_company


def _read_media(media_base, filename):
    """Fixture media bytes, from an HTTP base or a local directory.

    `build_venue_fixture` writes the media to disk; requiring them to be
    HTTP-served first added a step whose only failure mode was serving a stale
    copy.
    """
    if "://" in media_base:
        with urllib.request.urlopen(media_base.rstrip("/") + "/" + filename) as resp:
            return resp.read()
    return (Path(media_base) / filename).read_bytes()


class Command(BaseCommand):
    help = ("Upsert a menu fixture (categories + items + images) into an EXISTING "
            "company. Never creates the tenant; additive/idempotent.")

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True)
        parser.add_argument("--branch", action="append", dest="branches", default=None)
        parser.add_argument("--fixture", default=None)
        parser.add_argument("--media-base", dest="media_base", default=None)
        parser.add_argument("--strict", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        slug = opts["company"]
        try:
            company = Company.objects.get(slug=slug)
        except Company.DoesNotExist:
            raise CommandError(f"No company with slug '{slug}' — create the tenant first.")

        fixture_path = Path(opts["fixture"] or
                            Path(settings.BASE_DIR) / "menu" / "fixtures" / f"{slug}.json")
        if not fixture_path.exists():
            raise CommandError(f"Fixture not found: {fixture_path}")
        data = json.loads(fixture_path.read_text())

        if opts["branches"]:
            branches = list(Branch.all_objects.filter(company=company,
                                                      slug__in=opts["branches"]))
            found = {b.slug for b in branches}
            for want in opts["branches"]:
                if want not in found:
                    raise CommandError(f"Branch '{want}' not found in company '{slug}'.")
        else:
            branches = list(Branch.all_objects.filter(company=company))

        token = set_current_company(company)
        try:
            with transaction.atomic():
                self._upsert_catalog(company, branches, data, opts)
                if opts["dry_run"]:
                    transaction.set_rollback(True)
                    self.stdout.write(self.style.WARNING("dry-run — rolled back."))
            if not opts["dry_run"]:
                self._apply_images(company, opts)
        finally:
            reset_current_company(token)

    def _upsert_catalog(self, company, branches, data, opts):
        from menu.models import SubCategory, BranchSubCategory
        self._cat_by_slug, self._sub_by_key = {}, {}
        for cd in data.get("categories", []):
            cat, _ = publish.ensure_category(
                company, branches, name=cd["name"], slug=cd["slug"],
                display_order=cd.get("display_order", 0),
                icon_key=cd.get("icon_key", ""), hours_note=cd.get("hours_note", ""),
                update=True)   # the fixture is the source of truth for an import
            self._cat_by_slug[cd["slug"]] = cat
            for sd in cd.get("subcategories", []):
                sub, _ = SubCategory.all_objects.update_or_create(
                    company=company, category=cat, name=sd["name"],
                    defaults={"icon_key": sd.get("icon_key", "subAll"),
                              "display_order": sd.get("display_order", 0)})
                self._sub_by_key[(cd["slug"], sd["name"])] = sub
                for b in branches:
                    BranchSubCategory.objects.get_or_create(
                        branch=b, sub_category=sub,
                        defaults={"display_order": sd.get("display_order", 0)})

        self._items = []
        for it in data.get("items", []):
            cat = self._cat_by_slug[it["cat"]] if it.get("cat") else None
            sub = self._sub_by_key.get((it["cat"], it["sub"])) if it.get("sub") else None
            item, _ = publish.upsert_menu_item(
                company, branches if cat is not None else [], slug=it["slug"],
                name=it["name"], description=it.get("description", ""),
                price=it["price"], dietary_tags=it.get("tags", []),
                category=cat, sub_category=sub, display_order=it.get("order", 0),
                popular=it.get("popular", False), featured=it.get("featured", False))
            self._items.append((item, it))

    def _apply_images(self, company, opts):
        media_base = opts.get("media_base")
        for item, rec in self._items:
            img = rec.get("image")
            if not img:
                continue
            if not media_base:
                raise CommandError("--media-base is required when items carry images.")
            tmpdir = Path(settings.MEDIA_ROOT) / "_import_tmp"
            tmpdir.mkdir(parents=True, exist_ok=True)
            dest = tmpdir / f"{item.slug}.webp"
            try:
                payload = _read_media(media_base, img["file"])
                Image.open(BytesIO(payload)).verify()   # reject non-images
                dest.write_bytes(payload)
            except Exception as exc:
                if opts.get("strict"):
                    raise CommandError(f"image download failed for {item.slug}: {exc}")
                self.stderr.write(f"  ! image download failed for {item.slug}: {exc}")
                continue
            item.image_url, item.focal_x, item.focal_y = publish.copy_image_to_tenant(
                company, item.slug, dest)
            item.save(update_fields=["image_url", "focal_x", "focal_y"])
            dest.unlink(missing_ok=True)
        self.stdout.write(self.style.SUCCESS(
            f"Imported {len(self._items)} items into '{company.slug}'."))
