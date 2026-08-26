"""Task 3.4 — printable bill-summary PDF (B3/B4 print).

Same fixture shape as Task 3.1/3.3's billing tests:
  - Bikash: Milk Coffee (90) + French Toast (210) -> subtotal 300
  - Sita: Latte x2 (360) -> subtotal 360
Table total across both open sessions = 660.

Non-POS boundary: this endpoint only renders and returns a PDF. No payment,
no mutation, no stored receipt — these tests only assert response shape
(status, content-type, non-empty PDF body) and, for content correctness,
exercise the pure context-building helper directly rather than parsing PDF
bytes.
"""
from django.contrib.auth import get_user_model

from menu.dashboard.billing import table_total
from menu.dashboard.views import _bill_pdf_context
from menu.models import Branch, Company, GuestSession, Order, OrderItem, Table
from menu.tenancy import reset_current_company, set_current_company
from menu.tests.base import TenantTestCase


class BillSummaryPdfTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        U = get_user_model()
        self.owner = U.objects.create_user('boss34', password='pass')
        self.make_owner(self.owner)
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')
        self.table = Table.objects.create(branch=self.branch, label='7')

        self.bikash = GuestSession.objects.create(
            branch=self.branch, table=self.table, token='tok-bikash-34', label='Guest A', name='Bikash')
        self.sita = GuestSession.objects.create(
            branch=self.branch, table=self.table, token='tok-sita-34', label='Guest B', name='Sita')

        order_b = Order.objects.create(branch=self.branch, table=self.table, guest_session=self.bikash)
        OrderItem.objects.create(order=order_b, name='Milk Coffee', unit_price=90, qty=1)
        OrderItem.objects.create(order=order_b, name='French Toast', unit_price=210, qty=1)

        order_s = Order.objects.create(branch=self.branch, table=self.table, guest_session=self.sita)
        OrderItem.objects.create(order=order_s, name='Latte', unit_price=180, qty=2)

        self.login_as(self.owner)

    # --- combine mode ---

    def test_combine_pdf_returns_200_pdf(self):
        r = self.client.get(f'/dashboard/orders/table/{self.table.pk}/bill/print/?mode=combine')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        body = r.content
        self.assertTrue(body.startswith(b'%PDF'))
        self.assertGreater(len(body), 0)

    def test_combine_pdf_context_has_correct_table_total(self):
        from menu.dashboard.billing import table_sessions
        sessions = table_sessions(self.branch, self.table)
        context = _bill_pdf_context(self.table, sessions, 'combine')
        expected = table_total(self.branch, self.table)
        self.assertEqual(expected, 660)
        self.assertEqual(context['combined_total'], expected)

    # --- split mode ---

    def test_split_pdf_default_returns_200_pdf(self):
        r = self.client.get(f'/dashboard/orders/table/{self.table.pk}/bill/print/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))

    def test_split_pdf_context_has_both_guests(self):
        from menu.dashboard.billing import table_sessions
        sessions = table_sessions(self.branch, self.table)
        context = _bill_pdf_context(self.table, sessions, 'split')
        names = [g['session'].display_name for g in context['guests']]
        self.assertIn('Bikash', names)
        self.assertIn('Sita', names)
        subtotals = {g['session'].display_name: g['subtotal'] for g in context['guests']}
        self.assertEqual(subtotals['Bikash'], 300)
        self.assertEqual(subtotals['Sita'], 360)

    # --- single-guest print (per-guest Print button) ---

    def test_single_guest_pdf_returns_200_pdf(self):
        r = self.client.get(f'/dashboard/orders/table/{self.table.pk}/bill/print/{self.bikash.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))

    def test_single_guest_pdf_context_only_has_that_guest(self):
        from menu.dashboard.billing import table_sessions
        sessions = table_sessions(self.branch, self.table)
        context = _bill_pdf_context(self.table, sessions, 'split', session_id=self.bikash.pk)
        self.assertEqual(len(context['guests']), 1)
        self.assertEqual(context['guests'][0]['session'].pk, self.bikash.pk)
        self.assertEqual(context['guests'][0]['subtotal'], 300)
        self.assertTrue(context['single_guest'])

    def test_single_guest_pdf_unknown_session_is_404(self):
        r = self.client.get(f'/dashboard/orders/table/{self.table.pk}/bill/print/999999/')
        self.assertEqual(r.status_code, 404)

    # --- takeaway ---

    def test_takeaway_combine_pdf_returns_200(self):
        GuestSession.objects.create(
            branch=self.branch, table=None, token='tok-takeaway-34', label='Guest A', name='Ram')
        r = self.client.get('/dashboard/orders/table/takeaway/bill/print/?mode=combine')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))

    # --- fail-closed tenancy ---

    def test_foreign_company_table_pdf_is_404(self):
        other = Company.objects.create(name='Other', slug='other')
        tok = set_current_company(other)
        try:
            fbranch = Branch.objects.create(company=other, name='Far', slug='far')
            ftable = Table.objects.create(branch=fbranch, label='1')
        finally:
            reset_current_company(tok)
        r = self.client.get(f'/dashboard/orders/table/{ftable.pk}/bill/print/?mode=combine')
        self.assertEqual(r.status_code, 404)

    def test_foreign_company_session_id_pdf_is_404(self):
        """A session id from another company's table must not be printable
        through this table's PDF route, even though both ids exist."""
        other = Company.objects.create(name='Other', slug='other')
        tok = set_current_company(other)
        try:
            fbranch = Branch.objects.create(company=other, name='Far', slug='far')
            ftable = Table.objects.create(branch=fbranch, label='1')
            fsession = GuestSession.objects.create(
                branch=fbranch, table=ftable, token='tok-far-34', label='Guest A', name='Foreigner')
        finally:
            reset_current_company(tok)
        r = self.client.get(f'/dashboard/orders/table/{self.table.pk}/bill/print/{fsession.pk}/')
        self.assertEqual(r.status_code, 404)

    # --- non-POS: read-only, no mutation ---

    def test_pdf_does_not_close_sessions_or_create_orders(self):
        order_count_before = Order.objects.count()
        self.client.get(f'/dashboard/orders/table/{self.table.pk}/bill/print/?mode=combine')
        self.assertEqual(Order.objects.count(), order_count_before)
        self.bikash.refresh_from_db()
        self.sita.refresh_from_db()
        self.assertIsNone(self.bikash.closed_at)
        self.assertIsNone(self.sita.closed_at)
