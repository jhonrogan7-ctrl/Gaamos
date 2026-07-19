from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase

from menu.models import (
    Company, Branch, Category, SubCategory, MenuItem,
    BranchCategory, BranchSubCategory, BranchMenuItem, BranchItemPlacement,
)
from menu.tenancy import set_current_company, reset_current_company

THEMES = {
    'your-classic-cafe': 'fastfood', 'your-citrus-cafe': 'citrus',
    'your-contrast-cafe': 'contrast', 'your-eco-hotel': 'eco',
    'your-cozy-hotel': 'cozy', 'your-herbal-hotel': 'herbal',
}


class SeedShowcaseTest(TestCase):
    def tearDown(self):
        token = set_current_company(None)
        reset_current_company(token)
        super().tearDown()

    def _company(self):
        return Company.objects.get(slug='showcase')

    def test_creates_company_and_six_themed_branches(self):
        call_command('seed_showcase')
        company = self._company()
        self.assertEqual(company.name, 'Gaamos Showcase')
        self.assertEqual(company.menu_theme, 'citrus')
        branches = Branch.all_objects.filter(company=company)
        self.assertEqual(branches.count(), 6)
        for b in branches:
            self.assertEqual(b.menu_theme, THEMES[b.slug],
                             f"{b.slug} theme mismatch")

    def test_catalog_counts(self):
        call_command('seed_showcase')
        company = self._company()
        self.assertEqual(Category.all_objects.filter(company=company).count(), 8)
        self.assertEqual(SubCategory.all_objects.filter(company=company).count(), 34)
        self.assertEqual(MenuItem.all_objects.filter(company=company).count(), 238)

    def test_full_menu_placed_in_every_branch(self):
        call_command('seed_showcase')
        company = self._company()
        for b in Branch.all_objects.filter(company=company):
            self.assertEqual(BranchCategory.objects.filter(branch=b).count(), 8)
            self.assertEqual(BranchSubCategory.objects.filter(branch=b).count(), 34)
            self.assertEqual(BranchMenuItem.objects.filter(branch=b).count(), 238)
            self.assertEqual(BranchItemPlacement.objects.filter(branch=b).count(), 238)

    def test_every_item_has_a_resolvable_static_image(self):
        call_command('seed_showcase')
        company = self._company()
        thumbs = Path(settings.BASE_DIR) / 'static' / 'seed' / 'showcase' / 'thumbs'
        items = MenuItem.all_objects.filter(company=company)
        for it in items:
            self.assertTrue(it.image_url.startswith('/static/seed/showcase/thumbs/'))
            self.assertTrue((thumbs / it.image_url.rsplit('/', 1)[1]).is_file())

    def test_is_idempotent(self):
        call_command('seed_showcase')
        counts = (MenuItem.all_objects.count(), SubCategory.all_objects.count(),
                  BranchItemPlacement.objects.count())
        call_command('seed_showcase')
        self.assertEqual(
            (MenuItem.all_objects.count(), SubCategory.all_objects.count(),
             BranchItemPlacement.objects.count()), counts)
        self.assertEqual(Company.objects.filter(slug='showcase').count(), 1)

    def test_does_not_touch_other_tenants(self):
        call_command('seed_juicery')
        juicery = Company.objects.get(slug='juicery')
        before = MenuItem.all_objects.filter(company=juicery).count()
        call_command('seed_showcase')
        self.assertEqual(
            MenuItem.all_objects.filter(company=juicery).count(), before)
