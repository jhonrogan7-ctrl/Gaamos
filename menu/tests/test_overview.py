from django.contrib.auth.models import User
from django.utils import timezone

from menu.models import (
    Branch, Category, MenuItem, BranchItemPlacement, BranchVisit, Order, OrderItem,
)
from menu.tests.base import TenantTestCase


class OverviewLiveDataTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.owner = User.objects.create_user('boss', password='pass')
        self.make_owner(self.owner)
        self.login_as(self.owner)
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')
        self.cat = Category.objects.create(name='Juices', slug='juices', display_order=1)
        self.item = MenuItem.objects.create(company=self.company, name='Sea-Buckthorn', slug='sea-buckthorn', price=200)
        self.item2 = MenuItem.objects.create(company=self.company, name='Hidden Item', slug='hidden-item', price=100)
        BranchItemPlacement.objects.create(branch=self.branch, menu_item=self.item, category=self.cat)

    def test_items_live_and_hidden_reflect_placements(self):
        r = self.client.get('/dashboard/overview/')
        self.assertEqual(r.context['items_live'], 1)
        self.assertEqual(r.context['items_hidden'], 1)

    def test_scans_today_counts_only_todays_visits(self):
        BranchVisit.objects.create(branch=self.branch)
        BranchVisit.objects.create(branch=self.branch)
        old = BranchVisit.objects.create(branch=self.branch)
        old_dt = timezone.now() - timezone.timedelta(days=2)
        BranchVisit.objects.filter(pk=old.pk).update(created_at=old_dt)

        r = self.client.get('/dashboard/overview/')
        self.assertEqual(r.context['scans_today'], 2)

    def test_scans_delta_vs_yesterday(self):
        yesterday = timezone.now() - timezone.timedelta(days=1)
        for _ in range(2):
            v = BranchVisit.objects.create(branch=self.branch)
            BranchVisit.objects.filter(pk=v.pk).update(created_at=yesterday)
        for _ in range(4):
            BranchVisit.objects.create(branch=self.branch)

        r = self.client.get('/dashboard/overview/')
        self.assertEqual(r.context['scans_today'], 4)
        self.assertEqual(r.context['scans_delta'], {'pct': 100, 'dir': 'up'})

    def test_orders_and_revenue_today(self):
        Order.objects.create(branch=self.branch, total=300)
        Order.objects.create(branch=self.branch, total=150)
        r = self.client.get('/dashboard/overview/')
        self.assertEqual(r.context['orders_today'], 2)
        self.assertEqual(r.context['revenue_today'], 450)

    def _order_line(self, item, qty, branch=None):
        o = Order.objects.create(branch=branch or self.branch, total=item.price * qty)
        OrderItem.objects.create(order=o, menu_item=item, name=item.name,
                                 unit_price=item.price, qty=qty)
        return o

    def test_top_items_ranked_by_quantity_actually_ordered(self):
        self._order_line(self.item, 5)
        self._order_line(self.item2, 9)
        r = self.client.get('/dashboard/overview/')
        top = r.context['top_items']
        self.assertEqual(top[0]['name'], 'Hidden Item')
        self.assertEqual(top[0]['count'], 9)
        self.assertEqual(top[1]['name'], 'Sea-Buckthorn')
        self.assertEqual(top[1]['category'], 'Juices')

    def test_top_items_sums_quantity_across_orders(self):
        self._order_line(self.item, 2)
        self._order_line(self.item, 3)
        r = self.client.get('/dashboard/overview/')
        self.assertEqual(r.context['top_items'][0]['count'], 5)

    def test_top_items_ignores_stale_company_wide_order_count(self):
        # MenuItem.order_count is a company-wide counter; the panel must rank
        # from the branch-scoped order lines, not from it.
        MenuItem.objects.filter(pk=self.item2.pk).update(order_count=999)
        self._order_line(self.item, 1)
        r = self.client.get('/dashboard/overview/')
        names = [it['name'] for it in r.context['top_items']]
        self.assertEqual(names, ['Sea-Buckthorn'])

    def test_live_orders_feed_lists_recent_orders(self):
        o = Order.objects.create(branch=self.branch, total=300, table_label='7')
        OrderItem.objects.create(order=o, name='Sea-Buckthorn', unit_price=200, qty=1)
        r = self.client.get('/dashboard/overview/')
        body = r.content.decode()
        self.assertIn('Table 7', body)
        self.assertIn('Sea-Buckthorn', body)
        self.assertEqual(r.context['active_orders'], 1)

    def test_empty_state_has_no_sample_data(self):
        r = self.client.get('/dashboard/overview/')
        body = r.content.decode()
        self.assertNotIn('Sample data', body)
        self.assertIn('No orders yet.', body)

    def test_zero_both_days_renders_no_scans_yet_not_a_percentage(self):
        # Both days zero: there is no trend to state, so the tile must not
        # render a meaningless "0% vs yesterday".
        r = self.client.get('/dashboard/overview/')
        self.assertEqual(r.context['scans_delta'], {'pct': None, 'dir': 'flat'})
        self.assertIn('no scans yet', r.content.decode())

    def test_first_day_of_traffic_renders_new_today_not_divide_by_zero(self):
        # Yesterday zero, today non-zero: percent change is undefined (nothing
        # to divide by) — the tile says "new today" rather than erroring.
        BranchVisit.objects.create(branch=self.branch)
        r = self.client.get('/dashboard/overview/')
        self.assertEqual(r.context['scans_delta'], {'pct': None, 'dir': 'up'})
        self.assertIn('new today', r.content.decode())

    def test_decline_renders_down_arrow_and_down_class(self):
        yesterday = timezone.now() - timezone.timedelta(days=1)
        for _ in range(10):
            v = BranchVisit.objects.create(branch=self.branch)
            BranchVisit.objects.filter(pk=v.pk).update(created_at=yesterday)
        for _ in range(4):
            BranchVisit.objects.create(branch=self.branch)

        r = self.client.get('/dashboard/overview/')
        self.assertEqual(r.context['scans_delta'], {'pct': 60, 'dir': 'down'})
        body = r.content.decode()
        self.assertIn('delta down', body)   # red styling hook
        self.assertIn('▼ 60% vs yesterday', body)


class OverviewBranchScopingTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.branch_a = Branch.objects.create(company=self.company, name='A', slug='a')
        self.branch_b = Branch.objects.create(company=self.company, name='B', slug='b')
        self.manager = User.objects.create_user('mgr', password='pass')
        self.make_manager(self.manager, branches=[self.branch_a])
        self.login_as(self.manager)

    def test_manager_only_sees_own_branch_orders(self):
        Order.objects.create(branch=self.branch_a, total=100)
        Order.objects.create(branch=self.branch_b, total=999)
        r = self.client.get('/dashboard/overview/')
        self.assertEqual(r.context['orders_today'], 1)
        self.assertEqual(r.context['revenue_today'], 100)

    def test_manager_chart_label_is_own_branch_name(self):
        r = self.client.get('/dashboard/overview/')
        self.assertEqual(r.context['chart_branch_label'], 'A')

    def test_manager_top_items_exclude_other_branches_orders(self):
        # A dish ordered heavily at branch B must not appear in a branch-A
        # manager's "most ordered" — that would leak B's trade.
        item_a = MenuItem.objects.create(company=self.company, name='Mine',
                                         slug='mine', price=100)
        item_b = MenuItem.objects.create(company=self.company, name='Theirs',
                                         slug='theirs', price=100)
        for branch, item, qty in ((self.branch_a, item_a, 1),
                                  (self.branch_b, item_b, 50)):
            o = Order.objects.create(branch=branch, total=item.price * qty)
            OrderItem.objects.create(order=o, menu_item=item, name=item.name,
                                     unit_price=item.price, qty=qty)

        r = self.client.get('/dashboard/overview/')
        names = [it['name'] for it in r.context['top_items']]
        self.assertEqual(names, ['Mine'])
