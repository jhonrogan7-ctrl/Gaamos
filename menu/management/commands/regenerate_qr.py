"""Re-render every branch's stored QR poster.

Downloads render on demand, so they are always current — but the *stored*
thumbnail shown on the QR screens is only written when someone presses
Generate. Branches created before the poster design existed therefore keep an
old-looking preview indefinitely. This command refreshes them in bulk.
"""
from django.core.management.base import BaseCommand

from menu.dashboard.utils import generate_qr_for_branch
from menu.models import Branch, Company
from menu.tenancy import reset_current_company, set_current_company


class Command(BaseCommand):
    help = "Re-render stored branch QR posters (all tenants, or one --company)."

    def add_arguments(self, parser):
        parser.add_argument('--company', help='Company slug; default = every company.')
        parser.add_argument(
            '--base-url',
            help='Origin to encode, e.g. https://chillzone.zxyn.online. '
                 'Defaults to https://<slug>.<BASE_DOMAIN> per company.')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        from django.conf import settings

        companies = Company.objects.all()
        if opts['company']:
            companies = companies.filter(slug=opts['company'])
            if not companies.exists():
                self.stderr.write(self.style.ERROR(
                    f"No company with slug {opts['company']!r}"))
                return

        total = 0
        for company in companies:
            base_url = opts['base_url'] or f"https://{company.slug}.{settings.BASE_DOMAIN}"
            token = set_current_company(company)
            try:
                for branch in Branch.objects.all():
                    if opts['dry_run']:
                        self.stdout.write(f"would regenerate {company.slug}/{branch.slug}"
                                          f" -> {base_url}/?branch={branch.slug}")
                    else:
                        generate_qr_for_branch(branch, base_url)
                        self.stdout.write(f"regenerated {company.slug}/{branch.slug}")
                    total += 1
            finally:
                reset_current_company(token)

        verb = 'would regenerate' if opts['dry_run'] else 'regenerated'
        self.stdout.write(self.style.SUCCESS(f"{verb} {total} branch QR poster(s)"))
