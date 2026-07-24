"""Create or update a tenant shell from a venue fixture's `venue` block.

The generic replacement for the per-venue `seed_<venue>` commands: company +
branches, and nothing else. The catalog belongs to `import_menu`, so re-seeding
a live venue cannot undo its own dashboard edits.

Example:
  python manage.py seed_venue --fixture menu/fixtures/chillzone.json
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from menu.models import Branch, Company

COMPANY_FIELDS = ('name', 'tagline', 'phone', 'email',
                  'instagram', 'facebook', 'tiktok')


class Command(BaseCommand):
    help = ('Create/update a company and its branches from a venue fixture. '
            'Tenant shell only — no categories, no items, no deletes.')

    def add_arguments(self, parser):
        parser.add_argument('--fixture', required=True,
                            help='Path to menu/fixtures/<company>.json.')

    @transaction.atomic
    def handle(self, *args, **opts):
        path = Path(opts['fixture'])
        if not path.exists():
            raise CommandError(f'Fixture not found: {path}')
        venue = json.loads(path.read_text()).get('venue')
        if not venue:
            raise CommandError(f'{path} has no `venue` block — rebuild it with '
                               'build_venue_fixture.')
        slug = (venue.get('slug') or '').strip()
        if not slug:
            raise CommandError("venue.slug is empty — set `slug` in the sheet's "
                               '## Venue table.')

        defaults = {f: venue.get(f, '') or '' for f in COMPANY_FIELDS}
        defaults['name'] = defaults['name'] or slug
        defaults['status'] = 'active'
        company, created = Company.objects.update_or_create(
            slug=slug, defaults=defaults)

        for b in venue.get('branches', []):
            Branch.all_objects.update_or_create(
                company=company, slug=b['slug'],
                defaults={'name': b.get('name', '') or company.name,
                          'address': b.get('address', '') or '',
                          'tag': b.get('tag', '') or ''})

        verb = 'Created' if created else 'Updated'
        self.stdout.write(self.style.SUCCESS(
            f"{verb} '{company.slug}' as {company.name}: "
            f"{Branch.all_objects.filter(company=company).count()} branch(es). "
            f"Load the catalog with: python manage.py import_menu "
            f"--company {company.slug} --fixture {path}"))
