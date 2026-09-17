from menu.dashboard.billing import (
    table_sessions,
    session_lines,
    session_subtotal,
    table_total,
)
from menu.models import Branch, GuestSession, Order, OrderItem, Table
from menu.tests.base import TenantTestCase


class BillingHelpersTest(TenantTestCase):
    """Task 3.1 — pure per-table bill-computation helpers.

    Seeds one table with two open guest sessions:
      - Bikash: Milk Coffee (90) + French Toast (210) -> subtotal 300
      - Sita: Latte x2 (360) -> subtotal 360
    Table total across both open sessions = 660.
    """

    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')
        self.table = Table.objects.create(branch=self.branch, label='7')

        self.bikash = GuestSession.objects.create(
            branch=self.branch, table=self.table, token='tok-bikash', label='Guest A', name='Bikash')
        self.sita = GuestSession.objects.create(
            branch=self.branch, table=self.table, token='tok-sita', label='Guest B', name='Sita')

        order_b = Order.objects.create(branch=self.branch, table=self.table, guest_session=self.bikash)
        OrderItem.objects.create(order=order_b, name='Milk Coffee', unit_price=90, qty=1)
        OrderItem.objects.create(order=order_b, name='French Toast', unit_price=210, qty=1)

        order_s = Order.objects.create(branch=self.branch, table=self.table, guest_session=self.sita)
        OrderItem.objects.create(order=order_s, name='Latte', unit_price=180, qty=2)

    def test_table_sessions_returns_open_sessions_ordered_by_created_at(self):
        sessions = table_sessions(self.branch, self.table)
        self.assertEqual([s.id for s in sessions], [self.bikash.id, self.sita.id])

    def test_table_sessions_excludes_closed_sessions(self):
        from django.utils import timezone
        self.bikash.closed_at = timezone.now()
        self.bikash.save()

        sessions = table_sessions(self.branch, self.table)
        self.assertEqual([s.id for s in sessions], [self.sita.id])

    def test_session_subtotal_bikash(self):
        self.assertEqual(session_subtotal(self.bikash), 300)

    def test_session_subtotal_sita(self):
        self.assertEqual(session_subtotal(self.sita), 360)

    def test_table_total_sums_open_sessions(self):
        self.assertEqual(table_total(self.branch, self.table), 660)

    def test_session_lines_bikash_has_two_distinct_items(self):
        lines = session_lines(self.bikash)
        self.assertEqual(set(lines), {
            ('Milk Coffee', 1, 90),
            ('French Toast', 1, 210),
        })

    def test_session_lines_aggregates_duplicate_item_names(self):
        # Sita's single order-item is already qty=2; add a second OrderItem with
        # the same name in a second order for the same session to prove
        # aggregation happens across orders, not just within one OrderItem.
        order_s2 = Order.objects.create(branch=self.branch, table=self.table, guest_session=self.sita)
        OrderItem.objects.create(order=order_s2, name='Latte', unit_price=180, qty=1)

        lines = session_lines(self.sita)
        self.assertEqual(lines, [('Latte', 3, 540)])

    def test_session_lines_merges_item_across_two_separate_orders(self):
        # Bikash orders another Milk Coffee in a brand-new order within the same session.
        order_b2 = Order.objects.create(branch=self.branch, table=self.table, guest_session=self.bikash)
        OrderItem.objects.create(order=order_b2, name='Milk Coffee', unit_price=90, qty=1)

        lines = session_lines(self.bikash)
        self.assertEqual(set(lines), {
            ('Milk Coffee', 2, 180),
            ('French Toast', 1, 210),
        })
        self.assertEqual(session_subtotal(self.bikash), 390)
