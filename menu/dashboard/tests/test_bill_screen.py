"""Task 3.3 — table detail (B2) + Split/Combine bill screen (B3/B4).

Seeds one table with two open guest sessions (same fixture shape as Task 3.1's
BillingHelpersTest):
  - Bikash: Milk Coffee (90) + French Toast (210) -> subtotal 300
  - Sita: Latte x2 (360) -> subtotal 360
Table total across both open sessions = 660.
"""
from django.contrib.auth import get_user_model

from menu.models import Branch, Company, GuestSession, Order, OrderItem, Table
from menu.tenancy import reset_current_company, set_current_company
from menu.tests.base import TenantTestCase


class OrdersTableDetailAndBillTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        U = get_user_model()
        self.owner = U.objects.create_user('boss3', password='pass')
        self.make_owner(self.owner)
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')
        self.table = Table.objects.create(branch=self.branch, label='7')

        self.bikash = GuestSession.objects.create(
            branch=self.branch, table=self.table, token='tok-bikash-3', label='Guest A', name='Bikash')
        self.sita = GuestSession.objects.create(
            branch=self.branch, table=self.table, token='tok-sita-3', label='Guest B', name='Sita')

        order_b = Order.objects.create(branch=self.branch, table=self.table, guest_session=self.bikash)
        OrderItem.objects.create(order=order_b, name='Milk Coffee', unit_price=90, qty=1)
        OrderItem.objects.create(order=order_b, name='French Toast', unit_price=210, qty=1)

        order_s = Order.objects.create(branch=self.branch, table=self.table, guest_session=self.sita)
        OrderItem.objects.create(order=order_s, name='Latte', unit_price=180, qty=2)

        self.login_as(self.owner)

    # --- B2: table detail ---

    def test_table_detail_lists_each_open_session_with_its_items(self):
        body = self.client.get(f'/dashboard/orders/table/{self.table.pk}/').content.decode()
        self.assertIn('Bikash', body)
        self.assertIn('Sita', body)
        self.assertIn('Milk Coffee', body)
        self.assertIn('French Toast', body)
        self.assertIn('Latte', body)

    def test_table_detail_has_bill_link(self):
        body = self.client.get(f'/dashboard/orders/table/{self.table.pk}/').content.decode()
        self.assertIn(f'/dashboard/orders/table/{self.table.pk}/bill/', body)

    def test_table_detail_excludes_closed_sessions(self):
        from django.utils import timezone
        self.sita.closed_at = timezone.now()
        self.sita.save()
        body = self.client.get(f'/dashboard/orders/table/{self.table.pk}/').content.decode()
        self.assertIn('Bikash', body)
        self.assertNotIn('Sita', body)

    def test_table_detail_takeaway_returns_200(self):
        GuestSession.objects.create(
            branch=self.branch, table=None, token='tok-takeaway-3', label='Guest A', name='Ram')
        r = self.client.get('/dashboard/orders/table/takeaway/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('Ram', r.content.decode())

    # --- B3/B4: bill split / combine ---

    def test_bill_split_shows_per_guest_subtotals(self):
        body = self.client.get(f'/dashboard/orders/table/{self.table.pk}/bill/?mode=split').content.decode()
        self.assertIn('Bikash', body)
        self.assertIn('Sita', body)
        self.assertIn('Rs 300', body)  # Bikash subtotal
        self.assertIn('Rs 360', body)  # Sita subtotal

    def test_bill_defaults_to_split_mode(self):
        body = self.client.get(f'/dashboard/orders/table/{self.table.pk}/bill/').content.decode()
        self.assertIn('Rs 300', body)
        self.assertIn('Rs 360', body)

    def test_bill_combine_shows_single_total_equal_to_table_total(self):
        from menu.dashboard.billing import table_total
        expected = table_total(self.branch, self.table)
        self.assertEqual(expected, 660)
        body = self.client.get(f'/dashboard/orders/table/{self.table.pk}/bill/?mode=combine').content.decode()
        self.assertIn(f'Rs {expected}', body)

    def test_bill_has_close_table_and_preview_links(self):
        body = self.client.get(f'/dashboard/orders/table/{self.table.pk}/bill/').content.decode()
        self.assertIn(f'/dashboard/orders/table/{self.table.pk}/close/', body)
        self.assertIn('Preview receipt', body)

    def test_bill_split_has_per_guest_print_links(self):
        body = self.client.get(f'/dashboard/orders/table/{self.table.pk}/bill/?mode=split').content.decode()
        self.assertIn(f'/dashboard/orders/table/{self.table.pk}/bill/print/{self.bikash.pk}/', body)

    # --- fail-closed tenancy ---

    def test_table_detail_other_company_table_is_404(self):
        other = Company.objects.create(name='Other', slug='other')
        tok = set_current_company(other)
        try:
            fbranch = Branch.objects.create(company=other, name='Far', slug='far')
            ftable = Table.objects.create(branch=fbranch, label='1')
        finally:
            reset_current_company(tok)
        r = self.client.get(f'/dashboard/orders/table/{ftable.pk}/')
        self.assertEqual(r.status_code, 404)

    def test_bill_other_company_table_is_404(self):
        other = Company.objects.create(name='Other', slug='other')
        tok = set_current_company(other)
        try:
            fbranch = Branch.objects.create(company=other, name='Far', slug='far')
            ftable = Table.objects.create(branch=fbranch, label='1')
        finally:
            reset_current_company(tok)
        r = self.client.get(f'/dashboard/orders/table/{ftable.pk}/bill/')
        self.assertEqual(r.status_code, 404)
