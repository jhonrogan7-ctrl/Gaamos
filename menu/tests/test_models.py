from django.test import TestCase

from menu.models import Company, Branch, MenuItem, BranchMenuItem
from menu.tests.base import TenantTestCase


class CompanyModelTest(TestCase):
    def test_str(self):
        c = Company(name="The Juicery Cafe", tagline="Taste True Wellness",
                    phone="+977-123", email="a@b.com")
        self.assertEqual(str(c), "The Juicery Cafe")


class MenuItemDietaryTagsTest(TenantTestCase):
    def test_dietary_tags_roundtrip(self):
        item = MenuItem.objects.create(
            name="Test Dish", slug="test-dish",
            description="Desc", price=500, dietary_tags=["VEG", "GF"],
        )
        loaded = MenuItem.objects.get(pk=item.pk)
        self.assertEqual(loaded.dietary_tags, ["VEG", "GF"])

    def test_empty_dietary_tags(self):
        item = MenuItem.objects.create(
            name="Plain Dish", slug="plain-dish",
            description="Desc", price=300, dietary_tags=[],
        )
        loaded = MenuItem.objects.get(pk=item.pk)
        self.assertEqual(loaded.dietary_tags, [])


class BranchMenuItemTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(
            company=self.company, name='Main', slug='main', address='Lakeside'
        )
        self.item = MenuItem.objects.create(name='Dosa', slug='dosa', price=180)

    def test_effective_price_returns_override_when_set(self):
        bmi = BranchMenuItem.objects.create(
            branch=self.branch, menu_item=self.item, price_override=250
        )
        self.assertEqual(bmi.effective_price, 250)

    def test_effective_price_returns_template_when_no_override(self):
        bmi = BranchMenuItem.objects.create(
            branch=self.branch, menu_item=self.item, price_override=None
        )
        self.assertEqual(bmi.effective_price, 180)

    def test_unique_together_branch_menu_item(self):
        from django.db import IntegrityError
        BranchMenuItem.objects.create(branch=self.branch, menu_item=self.item)
        with self.assertRaises(IntegrityError):
            BranchMenuItem.objects.create(branch=self.branch, menu_item=self.item)


class CompanyMenuLayoutTest(TenantTestCase):
    def test_default_is_baseline(self):
        self.assertEqual(self.company.menu_layout, 'baseline')

    def test_choices(self):
        keys = {k for k, _ in Company.MENU_LAYOUT_CHOICES}
        self.assertEqual(keys, {'baseline', 'tabs', 'iconrail'})
