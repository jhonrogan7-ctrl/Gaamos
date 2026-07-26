"""Record a review verdict against a venue's generated images.

Everything in the sheet that is not explicitly rejected becomes `verified`: a
reviewer who read the page and rejected nothing has approved it, and that has
to be written down, because `build_venue_fixture --require-verified` reads
exactly this field.

Scoped to the sheet's own keys. The asset pool is shared across venues, so
signing off on Chill Zone must never sign off on Tranquility.
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from menu.models import ImageAsset
from menu.management.commands.review_images import read_sheet


class Command(BaseCommand):
    help = ('Mark a venue\'s generated images verified, except the keys passed '
            'to --reject. Scoped to the sheet.')

    def add_arguments(self, parser):
        parser.add_argument('--prompts', required=True,
                            help='Path to the venue prompt sheet (markdown).')
        parser.add_argument('--company', required=True,
                            help='Company slug; must match the sheet.')
        parser.add_argument('--source', default='flux',
                            help='ImageAsset.source to review (default: flux).')
        parser.add_argument('--reject', default='',
                            help='Comma-separated keys to reject.')
        parser.add_argument('--user', default=None,
                            help='Username to stamp as the reviewer.')

    def handle(self, *args, **opts):
        rows, _ = read_sheet(opts['prompts'], opts['company'])
        sheet_keys = {r['key'] for r in rows}
        rejected = {k.strip() for k in opts['reject'].split(',') if k.strip()}

        # A typo in a pasted key must not silently verify the image it meant to
        # reject — that is the one failure this command must never allow.
        stray = rejected - sheet_keys
        if stray:
            raise CommandError('not keys in this sheet: ' + ', '.join(sorted(stray)))

        reviewer = None
        if opts['user']:
            reviewer = User.objects.filter(username=opts['user']).first()
            if reviewer is None:
                raise CommandError(f"No such user: {opts['user']}")

        scoped = ImageAsset.objects.filter(source=opts['source'],
                                           found_for_slug__in=sheet_keys)
        stamp = {'reviewed_at': timezone.now(), 'reviewed_by': reviewer}
        n_rej = scoped.filter(found_for_slug__in=rejected).update(
            status='rejected', **stamp)
        # Never un-reject. A rejected row is a byte-level tombstone that
        # `intake.record` reads to refuse serving those bytes again, and a
        # re-roll leaves it in place beside the new asset for the same key —
        # so verifying the replacement must not resurrect what it replaced.
        n_ok = (scoped.exclude(found_for_slug__in=rejected)
                      .exclude(status='rejected')
                      .update(status='verified', **stamp))

        self.stdout.write(self.style.SUCCESS(
            f'verified {n_ok} | rejected {n_rej}'))
        if n_rej:
            self.stdout.write(
                'now re-roll them: generate_item_images --prompts <sheet> '
                '--reroll 1')
