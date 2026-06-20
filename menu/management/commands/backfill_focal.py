"""Compute focal points for existing item photos.

Run once after adding the focal_x/focal_y fields so the smart crop applies to
the current menu, not just future uploads:

    python manage.py backfill_focal          # only items still at center (50/50)
    python manage.py backfill_focal --all    # recompute every local image

Only locally stored images (under MEDIA_URL) are processed; externally hosted
image URLs are skipped since we don't fetch remote files here.
"""

import os

from django.conf import settings
from django.core.management.base import BaseCommand

from menu.imaging import compute_focal_point
from menu.models import MenuItem


class Command(BaseCommand):
    help = "Compute focal points for existing local item images."

    def add_arguments(self, parser):
        parser.add_argument(
            '--all', action='store_true',
            help='Recompute every item, not just those still at the 50/50 default.',
        )

    def handle(self, *args, **options):
        do_all = options['all']
        updated = skipped = missing = 0

        for item in MenuItem.objects.exclude(image_url=''):
            if not do_all and (item.focal_x, item.focal_y) != (50, 50):
                continue
            if not item.image_url.startswith(settings.MEDIA_URL):
                skipped += 1  # external URL — not a local file
                continue
            rel = item.image_url[len(settings.MEDIA_URL):].lstrip('/')
            path = os.path.join(settings.MEDIA_ROOT, rel)
            if not os.path.exists(path):
                missing += 1
                self.stderr.write(f"  missing file: {item.name} ({path})")
                continue
            item.focal_x, item.focal_y = compute_focal_point(path)
            item.save(update_fields=['focal_x', 'focal_y'])
            updated += 1
            self.stdout.write(f"  {item.name}: focal {item.focal_x}/{item.focal_y}")

        self.stdout.write(self.style.SUCCESS(
            f"Done. updated={updated} skipped(external)={skipped} missing={missing}"
        ))
