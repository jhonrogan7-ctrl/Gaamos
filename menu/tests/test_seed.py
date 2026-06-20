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
