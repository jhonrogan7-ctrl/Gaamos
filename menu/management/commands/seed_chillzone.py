import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from menu.models import (
    Company, Branch, Category, MenuItem,
    BranchMenuItem, BranchCategory, BranchItemPlacement,
)

COMPANY_SLUG = 'chillzone'
FIXTURE = Path(settings.BASE_DIR) / 'menu' / 'fixtures' / 'chillzone.json'


class Command(BaseCommand):
    help = ('Wipe and reseed the `chillzone` tenant as "Chill Zone" '
            '(full menu transcribed from the venue\'s physical menu).')

    @transaction.atomic
    def handle(self, *args, **options):
        data = json.loads(FIXTURE.read_text())

        c = data['company']
        company, _ = Company.objects.update_or_create(
            slug=COMPANY_SLUG,
            defaults={'name': c['name'], 'tagline': c['tagline'],
                      'phone': c['phone'], 'email': c['email'],
                      'instagram': c['instagram'], 'facebook': c['facebook'],
                      'tiktok': c['tiktok'], 'status': 'active'})

        fixture_branch_slugs = [b['slug'] for b in data['branches']]
        Branch.all_objects.filter(company=company).exclude(
            slug__in=fixture_branch_slugs).delete()
        Category.all_objects.filter(company=company).delete()   # cascades subs
        MenuItem.all_objects.filter(company=company).delete()

        branches = []
        for b in data['branches']:
            obj, _ = Branch.all_objects.update_or_create(
                company=company, slug=b['slug'],
                defaults={'name': b['name'], 'address': b['address'],
                          'tag': b['tag']})
            branches.append(obj)

        cat_by_slug = {}
        for cd in data['categories']:
            cat = Category.all_objects.create(
                company=company, slug=cd['slug'], name=cd['name'],
                icon_key=cd['icon_key'], hours_note=cd['hours_note'],
                display_order=cd['display_order'])
            cat_by_slug[cd['slug']] = cat
            for branch in branches:
                BranchCategory.objects.create(
                    branch=branch, category=cat,
                    display_order=cd['display_order'])

        for order, it in enumerate(data['items']):
            item = MenuItem.all_objects.create(
                company=company, slug=it['slug'], name=it['name'],
                description=it['description'], price=it['price'],
                dietary_tags=it['tags'], image_url=it['image'] or '',
                is_popular=it['popular'], is_featured=it['featured'])
            for branch in branches:
                BranchMenuItem.objects.create(branch=branch, menu_item=item)
                BranchItemPlacement.objects.create(
                    branch=branch, menu_item=item,
                    category=cat_by_slug[it['cat']], sub_category=None,
                    display_order=order)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded '{company.slug}' as {company.name}: "
            f"{MenuItem.all_objects.filter(company=company).count()} items across "
            f"{Branch.all_objects.filter(company=company).count()} branch(es)."))
