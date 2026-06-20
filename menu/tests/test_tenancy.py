from django.core.exceptions import ValidationError
from django.test import TestCase

from menu.models import Branch, BranchItemPlacement, BranchMenuItem, Company, Category, MenuItem
from menu.tenancy import (
    TenantContextRequired, set_current_company, reset_current_company,
)
from menu.tests.base import TenantTestCase


class FailClosedTest(TestCase):
    def setUp(self):
        self.a = Company.objects.create(name='A', slug='a')
        # seed a row via all_objects (no context needed)
        Category.all_objects.create(company=self.a, name='Coffee', slug='coffee')

    def test_no_context_raises(self):
        with self.assertRaises(TenantContextRequired):
            list(Category.objects.all())

    def test_escape_hatch_returns_all_without_context(self):
        rows = list(Category.all_objects.all())
        self.assertEqual(len(rows), 1)

    def test_base_manager_related_access_no_raise(self):
        # loading via all_objects and traversing relations must not raise
        sub_company = Category.all_objects.get(slug='coffee').company
        self.assertEqual(sub_company, self.a)


class ScopedQueryTest(TenantTestCase):
    def test_objects_scopes_to_active_company(self):
        other = Company.objects.create(name='B', slug='b')
        Category.all_objects.create(company=self.company, name='Mine', slug='shared')
        Category.all_objects.create(company=other, name='Theirs', slug='shared')
        names = set(Category.objects.values_list('name', flat=True))
        self.assertEqual(names, {'Mine'})

    def test_same_slug_allowed_across_companies(self):
        other = Company.objects.create(name='B', slug='b')
        Category.all_objects.create(company=self.company, name='X', slug='shared')
        # creating the same slug under another company must not violate uniqueness
        Category.all_objects.create(company=other, name='Y', slug='shared')
        self.assertEqual(Category.all_objects.filter(slug='shared').count(), 2)

    def test_duplicate_slug_within_company_rejected(self):
        from django.db import IntegrityError, transaction
        Category.all_objects.create(company=self.company, name='X', slug='dup')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Category.all_objects.create(company=self.company, name='Y', slug='dup')

    def test_autostamp_company_from_context(self):
        # within active context, create without explicit company stamps it
        item = MenuItem.objects.create(name='Latte', slug='latte', price=250)
        self.assertEqual(item.company, self.company)


class BranchRootedIntegrityTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.other = Company.objects.create(name='Other', slug='other')
        self.branch = Branch.all_objects.create(company=self.company, name='Main', slug='main', address='X')
        self.item_same = MenuItem.all_objects.create(company=self.company, name='A', slug='a', price=100)
        self.item_cross = MenuItem.all_objects.create(company=self.other, name='B', slug='b', price=100)

    def test_same_company_branch_item_ok(self):
        bmi = BranchMenuItem(branch=self.branch, menu_item=self.item_same)
        bmi.full_clean()  # should not raise
        bmi.save()
        self.assertEqual(bmi.effective_price, 100)

    def test_cross_company_branch_item_rejected(self):
        bmi = BranchMenuItem(branch=self.branch, menu_item=self.item_cross)
        with self.assertRaises(ValidationError):
            bmi.full_clean()
