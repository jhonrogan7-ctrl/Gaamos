"""Record the venues we already run into the global item library.

    python manage.py build_library \
        --company tranquility-inn --company chillzone \
        --company kailash-parbat --company pokhara-metro-eco

Idempotent: run it again and it finds every entry it made and changes nothing.
Pass every venue in one run -- `use_count` is set from the venues in the run,
not incremented, precisely so that re-running cannot inflate it.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from menu import library
from menu.models import Company, Item


class _Rollback(Exception):
    """--dry-run's way out of the transaction. Never escapes handle()."""


class Command(BaseCommand):
    help = ('Backfill the global item library from existing tenants '
            '(idempotent; nothing is written to a tenant menu).')

    def add_arguments(self, parser):
        parser.add_argument('--company', action='append', dest='companies',
                            required=True,
                            help='Company slug to read. Repeatable; pass every '
                                 'venue in one run so use_count is coherent.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would be written, then roll back.')
        parser.add_argument('--prune-drafts', action='store_true',
                            help='Delete every draft catalog Item. A draft is a '
                                 'scan-review row: this discards any review in '
                                 'flight as well as the stale ones.')
        parser.add_argument('--clear-rejected-live', action='store_true',
                            help='Blank the image on any live menu item whose '
                                 'picture is a rejected pool asset. A wrong '
                                 'photograph is a claim; blank beats wrong.')

    def handle(self, *args, **opts):
        companies = []
        for slug in opts['companies']:
            company = Company.objects.filter(slug=slug).first()
            if company is None:
                raise CommandError(f'No company with slug {slug!r}.')
            companies.append(company)

        try:
            with transaction.atomic():
                if opts['prune_drafts']:
                    pruned, _ = Item.objects.filter(status='draft').delete()
                    self.stdout.write(self.style.WARNING(
                        f'pruned {pruned} draft catalog row(s)'))
                report = library.backfill(
                    companies, clear_rejected_live=opts['clear_rejected_live'])
                self._report(report)
                if opts['dry_run']:
                    raise _Rollback
        except _Rollback:
            self.stdout.write(self.style.WARNING('dry run — rolled back'))
            return

        entries = Item.objects.filter(status='active')
        self.stdout.write(self.style.SUCCESS(
            f'library: {entries.count()} entries | '
            f'{entries.exclude(image_asset=None).count()} with an image | '
            f'{entries.filter(shareable=False).count()} not shareable'))

    def _report(self, report):
        self.stdout.write(
            f'created {report.created} | merged into an existing entry '
            f'{report.merged} | venue photographs {report.venue_photos} | '
            f'prompts composed {report.prompts_composed}')
        if report.rejected_live:
            self.stdout.write(self.style.ERROR(
                f'{len(report.rejected_live)} live menu item(s) show a REJECTED '
                f'image (not adopted into the library):'))
            for line in report.rejected_live:
                self.stdout.write(f'  ⊘ {line}')
        if report.cleared_live:
            self.stdout.write(self.style.WARNING(
                f'cleared {len(report.cleared_live)} live image(s): '
                + ', '.join(report.cleared_live)))
        if report.no_placement:
            self.stdout.write(self.style.WARNING(
                f'{len(report.no_placement)} item(s) have no category placement '
                f'and were skipped: ' + ', '.join(report.no_placement)))
