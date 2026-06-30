from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from menu.models import Branch, Company, Table, MenuItem, Order, OrderItem
from menu.tenancy import set_current_company, reset_current_company
from menu.tests.base import TenantTestCase


class OrderModelTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')

    def test_number_is_per_company_sequential(self):
        a = Order.objects.create(branch=self.branch)
        b = Order.objects.create(branch=self.branch)
        self.assertEqual(a.number, 1)
        self.assertEqual(b.number, 2)

    def test_takeaway_when_no_table(self):
        o = Order.objects.create(branch=self.branch)
        self.assertIsNone(o.table)
        self.assertEqual(o.table_label, '')

    def test_line_total_and_items(self):
        o = Order.objects.create(branch=self.branch, total=300)
        OrderItem.objects.create(order=o, name='Latte', unit_price=150, qty=2)
        self.assertEqual(o.items.first().line_total, 300)

    def test_clean_rejects_foreign_company_table(self):
        other = Company.objects.create(name='Other', slug='other')
        tok = set_current_company(other)
        try:
            fbranch = Branch.objects.create(company=other, name='Far', slug='far')
            ftable = Table.objects.create(branch=fbranch, label='1')
        finally:
            reset_current_company(tok)
        o = Order(company=self.company, branch=self.branch, table=ftable)
        with self.assertRaises(ValidationError):
            o.clean()
