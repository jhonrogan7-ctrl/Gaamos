"""Task 3.5 — close table (end guest sessions).

POSTing to the close route sets closed_at on every OPEN guest session at that
table (or, for Takeaway, every open session with table=None) and redirects
back to the orders queue. Non-POS boundary: no payment, no receipt, no Order
row is created/deleted/mutated — only the sessions are closed.
"""
from django.contrib.auth import get_user_model
from django.utils import timezone

from menu.models import Branch, Company, GuestSession, Order, OrderItem, Table
from menu.tenancy import reset_current_company, set_current_company
from menu.tests.base import TenantTestCase


class CloseTableTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        U = get_user_model()
        self.owner = U.objects.create_user('boss35', password='pass')
        self.make_owner(self.owner)
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')
        self.table = Table.objects.create(branch=self.branch, label='7')

        self.bikash = GuestSession.objects.create(
            branch=self.branch, table=self.table, token='tok-bikash-35', label='Guest A', name='Bikash')
        self.sita = GuestSession.objects.create(
            branch=self.branch, table=self.table, token='tok-sita-35', label='Guest B', name='Sita')

        self.order_b = Order.objects.create(branch=self.branch, table=self.table, guest_session=self.bikash)
        OrderItem.objects.create(order=self.order_b, name='Milk Coffee', unit_price=90, qty=1)

        self.order_s = Order.objects.create(branch=self.branch, table=self.table, guest_session=self.sita)
        OrderItem.objects.create(order=self.order_s, name='Latte', unit_price=180, qty=2)

        self.login_as(self.owner)

    def test_post_close_sets_closed_at_on_all_open_sessions(self):
        r = self.client.post(f'/dashboard/orders/table/{self.table.pk}/close/')
        self.assertEqual(r.status_code, 302)
        self.bikash.refresh_from_db()
        self.sita.refresh_from_db()
        self.assertIsNotNone(self.bikash.closed_at)
        self.assertIsNotNone(self.sita.closed_at)

    def test_post_close_redirects_to_orders_queue(self):
        r = self.client.post(f'/dashboard/orders/table/{self.table.pk}/close/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, '/dashboard/orders/')

    def test_post_close_does_not_touch_orders(self):
        order_count_before = Order.objects.count()
        item_count_before = OrderItem.objects.count()
        status_before = (self.order_b.status, self.order_s.status)
        self.client.post(f'/dashboard/orders/table/{self.table.pk}/close/')
        self.order_b.refresh_from_db()
        self.order_s.refresh_from_db()
        self.assertEqual(Order.objects.count(), order_count_before)
        self.assertEqual(OrderItem.objects.count(), item_count_before)
        self.assertEqual((self.order_b.status, self.order_s.status), status_before)

    def test_post_close_leaves_already_closed_sessions_alone(self):
        already = timezone.now()
        self.sita.closed_at = already
        self.sita.save(update_fields=['closed_at'])
        self.client.post(f'/dashboard/orders/table/{self.table.pk}/close/')
        self.sita.refresh_from_db()
        self.assertEqual(self.sita.closed_at, already)

    def test_get_close_is_not_allowed(self):
        r = self.client.get(f'/dashboard/orders/table/{self.table.pk}/close/')
        self.assertEqual(r.status_code, 405)
        self.bikash.refresh_from_db()
        self.assertIsNone(self.bikash.closed_at)

    def test_new_guest_after_close_starts_again_at_guest_a(self):
        self.client.post(f'/dashboard/orders/table/{self.table.pk}/close/')
        from menu.guest_sessions import _next_label
        self.assertEqual(_next_label(self.branch, self.table), 'Guest A')

    def test_close_other_company_table_is_404(self):
        other = Company.objects.create(name='Other', slug='other')
        tok = set_current_company(other)
        try:
            fbranch = Branch.objects.create(company=other, name='Far', slug='far')
            ftable = Table.objects.create(branch=fbranch, label='1')
        finally:
            reset_current_company(tok)
        r = self.client.post(f'/dashboard/orders/table/{ftable.pk}/close/')
        self.assertEqual(r.status_code, 404)

    def test_close_takeaway_sets_closed_at_and_get_is_405(self):
        ram = GuestSession.objects.create(
            branch=self.branch, table=None, token='tok-ram-35', label='Guest A', name='Ram')
        r = self.client.get('/dashboard/orders/table/takeaway/close/')
        self.assertEqual(r.status_code, 405)
        r = self.client.post('/dashboard/orders/table/takeaway/close/')
        self.assertEqual(r.status_code, 302)
        ram.refresh_from_db()
        self.assertIsNotNone(ram.closed_at)

    def test_bill_screen_close_form_posts_to_close_url(self):
        body = self.client.get(f'/dashboard/orders/table/{self.table.pk}/bill/').content.decode()
        self.assertIn(f'action="/dashboard/orders/table/{self.table.pk}/close/"', body)
        self.assertIn('method="post"', body.lower())
