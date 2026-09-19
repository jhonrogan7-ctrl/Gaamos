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

    def test_table_detail_has_back_link_to_orders(self):
        body = self.client.get(f'/dashboard/orders/table/{self.table.pk}/').content.decode()
        # The sidebar/tab-bar always link to Orders too, so this checks the
        # dedicated in-page back control, not just any occurrence of the href.
        self.assertIn('<a class="btn ghost" href="/dashboard/orders/">', body)

    def test_takeaway_detail_has_back_link_to_orders(self):
        body = self.client.get('/dashboard/orders/table/takeaway/').content.decode()
        self.assertIn('<a class="btn ghost" href="/dashboard/orders/">', body)

    def test_bill_screen_already_has_a_back_link_to_its_table(self):
        # Pre-existing (Task 3.3) — not new work, kept here as a regression
        # guard: confirms the "← Back to table" control Janak needed already
        # exists on THIS screen. His 09-19 report turned out to be about
        # order_detail (no back link at all there), not this one.
        body = self.client.get(f'/dashboard/orders/table/{self.table.pk}/bill/').content.decode()
        self.assertIn(f'href="/dashboard/orders/table/{self.table.pk}/"', body)
        self.assertIn('Back to table', body)

    def test_takeaway_bill_screen_already_has_a_back_link(self):
        body = self.client.get('/dashboard/orders/table/takeaway/bill/').content.decode()
        self.assertIn('href="/dashboard/orders/table/takeaway/"', body)
        self.assertIn('Back to table', body)

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

    # --- Task 8: pinned mobile action bars ---

    def test_table_detail_has_pinned_bill_action_bar(self):
        body = self.client.get(f'/dashboard/orders/table/{self.table.pk}/').content.decode()
        # `.actionbar` is used nowhere else in the dashboard templates; the
        # `Bill · Rs 660` label carries the middle dot + exact table total
        # (300 + 360), so it cannot collide with the `Bill · Table 7` page
        # title or the plain `Bill` header-action button.
        self.assertIn('actionbar', body)
        self.assertIn('Bill · Rs 660', body)
        self.assertEqual(self.client.get(
            f'/dashboard/orders/table/{self.table.pk}/').context['table_total'], 660)

    def test_table_detail_action_bar_total_matches_guest_subtotals(self):
        ctx = self.client.get(f'/dashboard/orders/table/{self.table.pk}/').context
        self.assertEqual(ctx['table_total'], sum(g['subtotal'] for g in ctx['guests']))

    def test_bill_screen_has_pinned_action_bar(self):
        body = self.client.get(f'/dashboard/orders/table/{self.table.pk}/bill/').content.decode()
        # `Preview receipt` and `Close table` are unique strings in the bill
        # template; both must live inside the single `.actionbar`.
        self.assertIn('actionbar', body)
        self.assertIn('Close table', body)
        self.assertIn('Preview receipt', body)
        self.assertIn('class="ab ghost"', body)
        self.assertIn('class="ab primary"', body)

    def test_bill_screen_action_bar_carries_inline_modifier(self):
        # D6b: the bill screen has no {% block header_action %} fallback, so its
        # action bar must carry .actionbar--inline — the CSS hook that makes
        # Preview/Close fall back to an in-flow row at >=900px instead of being
        # swallowed by `.actionbar { display: none }`. Table detail does NOT
        # carry it (it keeps its header Bill button on desktop).
        bill = self.client.get(
            f'/dashboard/orders/table/{self.table.pk}/bill/').content.decode()
        self.assertIn('actionbar--inline', bill)
        detail = self.client.get(
            f'/dashboard/orders/table/{self.table.pk}/').content.decode()
        self.assertNotIn('actionbar--inline', detail)

    def test_bill_screen_close_form_still_posts_to_close_url_with_csrf(self):
        body = self.client.get(f'/dashboard/orders/table/{self.table.pk}/bill/').content.decode()
        # close_url is an unchanged plain href built in _bill_context; the form
        # must still POST there and still ship a CSRF token.
        self.assertIn(f'action="/dashboard/orders/table/{self.table.pk}/close/"', body)
        self.assertIn('csrfmiddlewaretoken', body)
        self.assertIn('class="ab-form"', body)

    def test_bill_screen_non_pos_note_survives(self):
        body = self.client.get(f'/dashboard/orders/table/{self.table.pk}/bill/').content.decode()
        self.assertIn('Gaamos stays non-POS.', body)

    def test_bill_split_print_button_label_includes_guest_name(self):
        body = self.client.get(
            f'/dashboard/orders/table/{self.table.pk}/bill/?mode=split').content.decode()
        # bare `Print` was ambiguous across guests; the label now names the guest.
        self.assertIn('>Print Bikash<', body)
        self.assertIn('>Print Sita<', body)

    def test_takeaway_table_detail_has_action_bar(self):
        ram = GuestSession.objects.create(
            branch=self.branch, table=None, token='tok-ta-8', label='Guest A', name='Ram')
        ram_order = Order.objects.create(branch=self.branch, table=None, guest_session=ram)
        OrderItem.objects.create(order=ram_order, name='Momo', unit_price=180, qty=2)
        OrderItem.objects.create(order=ram_order, name='Chiya', unit_price=40, qty=1)
        body = self.client.get('/dashboard/orders/table/takeaway/').content.decode()
        self.assertIn('actionbar', body)
        # Pin the actual takeaway total the fixture produces (2*180 + 40 = 400):
        # a bare 'Bill · Rs' would still pass if table_total silently rendered empty.
        self.assertIn('Bill · Rs 400', body)
        self.assertEqual(
            self.client.get('/dashboard/orders/table/takeaway/').context['table_total'], 400)
        self.assertIn('/dashboard/orders/table/takeaway/bill/', body)

    def test_takeaway_bill_screen_has_action_bar(self):
        GuestSession.objects.create(
            branch=self.branch, table=None, token='tok-ta-8b', label='Guest A', name='Ram')
        body = self.client.get('/dashboard/orders/table/takeaway/bill/').content.decode()
        self.assertIn('actionbar', body)
        self.assertIn('Close table', body)
        self.assertIn('Preview receipt', body)
        self.assertIn('action="/dashboard/orders/table/takeaway/close/"', body)

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
