"""Ingest a menu fixture's collected images into the global ImageAsset pool as
`pending` rows for human verification.

Reuses the pipeline `intake.record` helper (dedup on origin_url/content_hash,
rejected-tombstone skip). Idempotent: re-running deposits nothing new. By
default embeddings are NOT computed (staff can verify without them; embeddings
are only needed once the reuse loop goes live) — pass --embed to compute them
via Gemini.

Example:
  python manage.py ingest_fixture_images \
      --fixture menu/fixtures/tranquility-inn-preview.json \
      --media-dir media/items/tranquility-inn
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from menu.pipeline import intake

# fixture `source` values → ImageAsset.source vocabulary
_SOURCE_MAP = {"found": "commons", "generated": "gemini"}


def _seed_tags(item):
    """Light initial tags for browse/filter: category + slug words + any item tags."""
    slug = item.get("slug", "")
    raw = [item.get("cat")] + slug.split("-") + list(item.get("tags") or [])
    seen, out = set(), []
    for t in raw:
        t = (t or "").strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


class Command(BaseCommand):
    help = ("Deposit a fixture's per-item images into the ImageAsset pool as "
            "pending (idempotent). Images read from --media-dir by image.file name.")

    def add_arguments(self, parser):
        parser.add_argument("--fixture", required=True)
        parser.add_argument("--media-dir", dest="media_dir", default=None,
                            help="Dir holding the webp files (default: "
                                 "MEDIA_ROOT/items/<company>).")
        parser.add_argument("--embed", action="store_true",
                            help="Compute Gemini embeddings now (default: skip).")

    def handle(self, *args, **opts):
        fixture_path = Path(opts["fixture"])
        if not fixture_path.exists():
            raise CommandError(f"Fixture not found: {fixture_path}")
        data = json.loads(fixture_path.read_text())

        company = data.get("company", "")
        media_dir = Path(opts["media_dir"] or
                         Path(settings.MEDIA_ROOT) / "items" / company)
        if not media_dir.exists():
            raise CommandError(f"Media dir not found: {media_dir}")

        embedder = None if opts["embed"] else (lambda text: None)

        from menu.models import ImageAsset
        before = ImageAsset.objects.count()
        processed = skipped = missing = 0
        for item in data.get("items", []):
            img = item.get("image")
            if not img:
                continue
            src_file = media_dir / img["file"]
            if not src_file.exists():
                self.stderr.write(f"  ! missing image file: {src_file}")
                missing += 1
                continue
            asset = intake.record(
                source=_SOURCE_MAP.get(img.get("source", ""), img.get("source", "")),
                webp_bytes=src_file.read_bytes(),
                item_name=item.get("name", ""),
                found_for_slug=item.get("slug", ""),
                source_text=item.get("description", ""),
                origin_url=img.get("origin_url") or "",
                prompt=img.get("prompt") or "",
                name=img["file"],
                tags=_seed_tags(item),
                embedder=embedder,
            )
            if asset is None:
                skipped += 1                       # rejected tombstone
            else:
                processed += 1

        created = ImageAsset.objects.count() - before
        existing = processed - created
        self.stdout.write(self.style.SUCCESS(
            f"Ingested from {fixture_path.name}: {created} new pending, "
            f"{existing} already present, {skipped} rejected-skipped, "
            f"{missing} missing files."))
