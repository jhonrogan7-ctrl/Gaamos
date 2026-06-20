from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from menu.models import Company, Membership


class Command(BaseCommand):
    help = 'Create (or update) an owner Membership for a company.'

    def add_arguments(self, parser):
        parser.add_argument('company_slug')
        parser.add_argument('username')
        parser.add_argument('--email', default='')
        parser.add_argument('--password', default=None)

    def handle(self, *args, **options):
        try:
            company = Company.objects.get(slug=options['company_slug'])
        except Company.DoesNotExist:
            raise CommandError(f"No company with slug '{options['company_slug']}'")

        user, created = User.objects.get_or_create(
            username=options['username'], defaults={'email': options['email']})
        if options['password']:
            user.set_password(options['password'])
        user.save()

        membership, _ = Membership.objects.update_or_create(
            user=user, company=company, defaults={'role': Membership.ROLE_OWNER})

        self.stdout.write(self.style.SUCCESS(
            f"{'Created' if created else 'Updated'} owner '{user.username}' for '{company.slug}'."))
