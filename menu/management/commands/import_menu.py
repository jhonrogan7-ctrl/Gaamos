import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from menu.models import Company, Branch
from menu.tenancy import set_current_company, reset_current_company


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
        finally:
            reset_current_company(token)

    def _upsert_catalog(self, company, branches, data, opts):
        # Filled in by later tasks.
        pass
