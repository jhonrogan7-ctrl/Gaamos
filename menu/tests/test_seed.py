from django.core.management import call_command
from django.test import TestCase

from menu.models import (
    Company, Branch, Category, SubCategory, MenuItem, BranchItemPlacement,
)
from menu.tenancy import set_current_company, reset_current_company


class SeedJuiceryTest(TestCase):
    def tearDown(self):
        # Ensure no tenant context leaks to subsequent tests across the suite.
        token = set_current_company(None)
        reset_current_company(token)
        super().tearDown()

    def test_seed_creates_juicery_with_stamped_rows(self):
        call_command('seed_juicery')
        company = Company.objects.get(slug='juicery')
        # every catalog row is stamped to the juicery company
        self.assertTrue(Branch.all_objects.filter(company=company).exists())
        self.assertTrue(Category.all_objects.filter(company=company).exists())
        self.assertTrue(MenuItem.all_objects.filter(company=company).exists())
        self.assertTrue(SubCategory.all_objects.filter(company=company).exists())
        self.assertEqual(MenuItem.all_objects.exclude(company=company).count(), 0)
        # placements link back to the same company through their branch
        token = set_current_company(company)
        try:
            placement_count = BranchItemPlacement.objects.filter(branch__company=company).count()
            self.assertGreater(placement_count, 0)
            for pl in BranchItemPlacement.objects.filter(branch__company=company):
                self.assertEqual(pl.branch.company_id, company.id)
        finally:
            reset_current_company(token)

    def test_seed_is_idempotent(self):
        call_command('seed_juicery')
        items_first = MenuItem.all_objects.count()
        from menu.models import BranchItemPlacement
        placements_first = BranchItemPlacement.objects.count()
        call_command('seed_juicery')
        self.assertEqual(MenuItem.all_objects.count(), items_first)
        self.assertEqual(Company.objects.filter(slug='juicery').count(), 1)
        self.assertEqual(BranchItemPlacement.objects.count(), placements_first)


class SeedTestcoTest(TestCase):
    def tearDown(self):
        token = set_current_company(None)
        reset_current_company(token)
        super().tearDown()

    def _company(self):
        return Company.objects.get(slug='testco')

    def test_seed_creates_danfe_house(self):
        call_command('seed_testco')
        company = self._company()
        self.assertEqual(company.name, 'Danfe House Kitchen & Bar')
        self.assertEqual(Branch.all_objects.filter(company=company).count(), 2)
        self.assertEqual(Category.all_objects.filter(company=company).count(), 8)
        self.assertEqual(SubCategory.all_objects.filter(company=company).count(), 17)
        self.assertEqual(MenuItem.all_objects.filter(company=company).count(), 68)
        # every item placed in BOTH branches
        self.assertEqual(
            BranchItemPlacement.objects.filter(branch__company=company).count(), 136)

    def test_seed_wipes_existing_junk(self):
        company, _ = Company.objects.update_or_create(
            slug='testco', defaults={'name': 'Test Co'})
        junk_branch = Branch.all_objects.create(
            company=company, name='new branch', slug='new-branch', address='x')
        junk_cat = Category.all_objects.create(
            company=company, name='gggg', slug='gggg')
        junk_item = MenuItem.all_objects.create(
            company=company, name='junk', slug='junk', price=1)
        call_command('seed_testco')
        self.assertFalse(Branch.all_objects.filter(pk=junk_branch.pk).exists())
        self.assertFalse(Category.all_objects.filter(pk=junk_cat.pk).exists())
        self.assertFalse(MenuItem.all_objects.filter(pk=junk_item.pk).exists())

    def test_seed_is_idempotent(self):
        call_command('seed_testco')
        counts = (MenuItem.all_objects.count(), SubCategory.all_objects.count(),
                  BranchItemPlacement.objects.count())
        call_command('seed_testco')
        self.assertEqual(
            (MenuItem.all_objects.count(), SubCategory.all_objects.count(),
             BranchItemPlacement.objects.count()), counts)
        self.assertEqual(Company.objects.filter(slug='testco').count(), 1)

    def test_seed_does_not_touch_other_tenants(self):
        call_command('seed_juicery')
        juicery = Company.objects.get(slug='juicery')
        before = MenuItem.all_objects.filter(company=juicery).count()
        call_command('seed_testco')
        self.assertEqual(MenuItem.all_objects.filter(company=juicery).count(), before)

    def test_patan_price_overrides(self):
        from menu.models import BranchMenuItem
        call_command('seed_testco')
        company = self._company()
        patan = Branch.all_objects.get(company=company, slug='patan')
        momo = MenuItem.all_objects.get(company=company, slug='chicken-momo')
        link = BranchMenuItem.objects.get(branch=patan, menu_item=momo)
        self.assertEqual(link.price_override, 240)
        self.assertEqual(link.effective_price, 240)
        thamel = Branch.all_objects.get(company=company, slug='thamel')
        link_t = BranchMenuItem.objects.get(branch=thamel, menu_item=momo)
        self.assertIsNone(link_t.price_override)
