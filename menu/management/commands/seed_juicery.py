import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from menu.models import (
    Company, Branch, Category, SubCategory, MenuItem,
    BranchMenuItem, BranchCategory, BranchSubCategory, BranchItemPlacement,
)

COMPANY_SLUG = 'juicery'
FIXTURE = Path(settings.BASE_DIR) / 'menu' / 'fixtures' / 'seed.json'


class Command(BaseCommand):
    help = 'Idempotently seed The Juicery Cafe as greenfield company `juicery`.'

    @transaction.atomic
    def handle(self, *args, **options):
        records = json.loads(FIXTURE.read_text())
        by_model = {}
        for rec in records:
            by_model.setdefault(rec['model'].split('.')[-1], []).append(rec)

        # 1) Company from the single donor restaurant row
        rest = (by_model.get('restaurant') or [{}])[0].get('fields', {})
        company, _ = Company.objects.update_or_create(
            slug=COMPANY_SLUG,
            defaults={
                'name': rest.get('name', 'The Juicery Cafe'),
                'tagline': rest.get('tagline', ''),
                'phone': rest.get('phone', ''),
                'email': rest.get('email', ''),
                'instagram': rest.get('instagram', ''),
                'facebook': rest.get('facebook', ''),
                'tiktok': rest.get('tiktok', ''),
                'status': 'active',
            },
        )

        # maps from donor PK -> new instance, so FK references resolve
        cat_map, sub_map, item_map, branch_map = {}, {}, {}, {}

        for rec in by_model.get('category', []):
            f = rec['fields']
            obj, _ = Category.all_objects.update_or_create(
                company=company, slug=f['slug'],
                defaults={'name': f['name'], 'icon_key': f.get('icon_key', ''),
                          'display_order': f.get('display_order', 0),
                          'hours_note': f.get('hours_note', '')})
            cat_map[rec['pk']] = obj

        for rec in by_model.get('subcategory', []):
            f = rec['fields']
            cat = cat_map[f['category']]
            obj, _ = SubCategory.all_objects.update_or_create(
                company=company, category=cat, name=f['name'],
                defaults={'icon_key': f.get('icon_key', 'subAll'),
                          'display_order': f.get('display_order', 0)})
            sub_map[rec['pk']] = obj

        for rec in by_model.get('menuitem', []):
            f = rec['fields']
            obj, _ = MenuItem.all_objects.update_or_create(
                company=company, slug=f['slug'],
                defaults={'name': f['name'], 'description': f.get('description', ''),
                          'price': f['price'], 'dietary_tags': f.get('dietary_tags', []),
                          'image_url': f.get('image_url', ''),
                          'focal_x': f.get('focal_x', 50), 'focal_y': f.get('focal_y', 50),
                          'is_popular': f.get('is_popular', False),
                          'is_featured': f.get('is_featured', False),
                          'order_count': f.get('order_count', 0)})
            item_map[rec['pk']] = obj

        for rec in by_model.get('branch', []):
            f = rec['fields']
            obj, _ = Branch.all_objects.update_or_create(
                company=company, slug=f['slug'],
                defaults={'name': f['name'], 'address': f.get('address', ''),
                          'tag': f.get('tag', ''), 'qr_image': f.get('qr_image', '')})
            branch_map[rec['pk']] = obj

        for rec in by_model.get('branchcategory', []):
            f = rec['fields']
            BranchCategory.objects.update_or_create(
                branch=branch_map[f['branch']], category=cat_map[f['category']],
                defaults={'display_order': f.get('display_order', 0)})

        for rec in by_model.get('branchsubcategory', []):
            f = rec['fields']
            BranchSubCategory.objects.update_or_create(
                branch=branch_map[f['branch']], sub_category=sub_map[f['sub_category']],
                defaults={'display_order': f.get('display_order', 0)})

        for rec in by_model.get('branchmenuitem', []):
            f = rec['fields']
            BranchMenuItem.objects.update_or_create(
                branch=branch_map[f['branch']], menu_item=item_map[f['menu_item']],
                defaults={'price_override': f.get('price_override')})

        for rec in by_model.get('branchitemplacement', []):
            f = rec['fields']
            BranchItemPlacement.objects.update_or_create(
                branch=branch_map[f['branch']], menu_item=item_map[f['menu_item']],
                category=cat_map[f['category']],
                sub_category=sub_map[f['sub_category']] if f.get('sub_category') else None,
                defaults={'display_order': f.get('display_order', 0)})

        self.stdout.write(self.style.SUCCESS(
            f"Seeded company '{company.slug}' with "
            f"{MenuItem.all_objects.filter(company=company).count()} items."))
