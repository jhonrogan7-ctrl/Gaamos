import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from menu.models import (
    Company, Branch, Category, SubCategory, MenuItem,
    BranchMenuItem, BranchCategory, BranchSubCategory, BranchItemPlacement,
)

COMPANY_SLUG = 'showcase'
FIXTURE = Path(settings.BASE_DIR) / 'menu' / 'fixtures' / 'showcase.json'

# (name, slug, menu_theme) — one branch per guest theme.
BRANCHES = [
    ('Your Classic Cafe',  'your-classic-cafe',  'fastfood'),
    ('Your Citrus Cafe',   'your-citrus-cafe',   'citrus'),
    ('Your Contrast Cafe', 'your-contrast-cafe', 'contrast'),
    ('Your Eco Hotel',     'your-eco-hotel',     'eco'),
    ('Your Cozy Hotel',    'your-cozy-hotel',    'cozy'),
    ('Your Herbal Hotel',  'your-herbal-hotel',  'herbal'),
]


class Command(BaseCommand):
    help = ('Idempotently (re)seed the `showcase` demo tenant: 6 themed branches, '
            'each carrying the identical Juicery menu.')

    @transaction.atomic
    def handle(self, *args, **options):
        data = json.loads(FIXTURE.read_text())

        c = data['company']
        company, _ = Company.objects.update_or_create(
            slug=COMPANY_SLUG,
            defaults={'name': 'Gaamos Showcase', 'tagline': c['tagline'],
                      'phone': c['phone'], 'email': c['email'],
                      'instagram': c['instagram'], 'facebook': c['facebook'],
                      'tiktok': c['tiktok'], 'status': 'active',
                      'menu_theme': 'citrus'})

        # Wipe: catalog is fully fixture-owned (cascades placements/links).
        # Branches not in BRANCHES go too; listed branches are updated in place.
        keep_slugs = [slug for _, slug, _ in BRANCHES]
        Branch.all_objects.filter(company=company).exclude(
            slug__in=keep_slugs).delete()
        Category.all_objects.filter(company=company).delete()  # cascades subs
        MenuItem.all_objects.filter(company=company).delete()

        branches = []
        for name, slug, theme in BRANCHES:
            obj, _ = Branch.all_objects.update_or_create(
                company=company, slug=slug,
                defaults={'name': name, 'address': '', 'tag': '',
                          'menu_theme': theme})
            branches.append(obj)

        cat_by_slug, sub_by_key = {}, {}
        for cd in data['categories']:
            cat = Category.all_objects.create(
                company=company, slug=cd['slug'], name=cd['name'],
                icon_key=cd['icon_key'], hours_note=cd['hours_note'],
                display_order=cd['display_order'])
            cat_by_slug[cd['slug']] = cat
            for sd in cd['subcategories']:
                sub = SubCategory.all_objects.create(
                    company=company, category=cat, name=sd['name'],
                    icon_key=sd['icon_key'], display_order=sd['display_order'])
                sub_by_key[(cd['slug'], sd['name'])] = sub
            for branch in branches:
                BranchCategory.objects.create(
                    branch=branch, category=cat, display_order=cd['display_order'])
                for sd in cd['subcategories']:
                    BranchSubCategory.objects.create(
                        branch=branch,
                        sub_category=sub_by_key[(cd['slug'], sd['name'])],
                        display_order=sd['display_order'])

        for it in data['items']:
            item = MenuItem.all_objects.create(
                company=company, slug=it['slug'], name=it['name'],
                description=it['description'], price=it['price'],
                dietary_tags=it['tags'], image_url=it['image'],
                is_popular=it['popular'], is_featured=it['featured'])
            sub = sub_by_key.get((it['cat'], it['sub'])) if it['sub'] else None
            for branch in branches:
                BranchMenuItem.objects.create(branch=branch, menu_item=item)
                BranchItemPlacement.objects.create(
                    branch=branch, menu_item=item,
                    category=cat_by_slug[it['cat']], sub_category=sub,
                    display_order=it['order'])

        self.stdout.write(self.style.SUCCESS(
            f"Seeded '{company.slug}' as {company.name}: "
            f"{MenuItem.all_objects.filter(company=company).count()} items across "
            f"{Branch.all_objects.filter(company=company).count()} branches."))
