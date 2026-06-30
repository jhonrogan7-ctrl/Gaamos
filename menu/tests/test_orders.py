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


import json


class PlaceOrderTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')
        self.item = MenuItem.objects.create(company=self.company, name='Latte', price=150)
        self.table = Table.objects.create(branch=self.branch, label='7', code='abc123')

    def _post(self, body):
        return self.client.post('/api/order/', data=json.dumps(body),
                                content_type='application/json')

    def test_creates_order_with_table_and_total(self):
        r = self._post({'branch': 'lake', 'table': 'abc123',
                        'items': [{'id': self.item.id, 'qty': 2}]})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data['ok'])
        o = Order.objects.get(number=data['number'])
        self.assertEqual(o.branch, self.branch)
        self.assertEqual(o.table, self.table)
        self.assertEqual(o.table_label, '7')
        self.assertEqual(o.total, 300)
        self.assertEqual(o.items.count(), 1)

    def test_takeaway_without_table(self):
        r = self._post({'branch': 'lake', 'items': [{'id': self.item.id, 'qty': 1}]})
        o = Order.objects.get(number=r.json()['number'])
        self.assertIsNone(o.table)
        self.assertEqual(o.table_label, '')

    def test_still_bumps_order_count(self):
        self._post({'branch': 'lake', 'items': [{'id': self.item.id, 'qty': 3}]})
        self.item.refresh_from_db()
        self.assertEqual(self.item.order_count, 3)

    def test_bad_body_400(self):
        r = self.client.post('/api/order/', data='not json', content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_empty_items_makes_no_order(self):
        r = self._post({'branch': 'lake', 'items': []})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)


class OrdersQueueTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        U = get_user_model()
        self.owner = U.objects.create_user('boss', password='pass')
        self.make_owner(self.owner)
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')
        self.order = Order.objects.create(branch=self.branch, table_label='7', total=300)
        OrderItem.objects.create(order=self.order, name='Latte', unit_price=150, qty=2)
        self.login_as(self.owner)

    def test_branch_queue_renders_real_order(self):
        body = self.client.get(f'/dashboard/branch/{self.branch.slug}/orders/queue/').content.decode()
        self.assertIn(f'#{self.order.number}', body)
        self.assertIn('Latte', body)
        self.assertIn('Rs 300', body)
        self.assertIn('Table 7', body)

    def test_global_queue_shows_branch_column(self):
        body = self.client.get('/dashboard/orders/queue/').content.decode()
        self.assertIn('Lake', body)  # branch name column
        self.assertIn(f'#{self.order.number}', body)

    def test_status_filter_new_excludes_served(self):
        served = Order.objects.create(branch=self.branch, status=Order.STATUS_SERVED, total=0)
        body = self.client.get('/dashboard/orders/queue/?status=new').content.decode()
        self.assertIn(f'#{self.order.number}', body)
        self.assertNotIn(f'#{served.number}', body)

    def test_serve_action_marks_served(self):
        self.client.post(f'/dashboard/order/{self.order.pk}/serve/')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_SERVED)

    def test_serve_forbidden_other_company(self):
        other = Company.objects.create(name='Other', slug='other')
        tok = set_current_company(other)
        try:
            fbranch = Branch.objects.create(company=other, name='Far', slug='far')
            forder = Order.objects.create(branch=fbranch, total=0)
        finally:
            reset_current_company(tok)
        r = self.client.post(f'/dashboard/order/{forder.pk}/serve/')
        self.assertEqual(r.status_code, 403)


class OrderStreamTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        U = get_user_model()
        self.owner = U.objects.create_user('boss', password='pass')
        self.make_owner(self.owner)
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')
        self.login_as(self.owner)

    def test_orders_payload_emits_new_order(self):
        from menu.dashboard.views import orders_payload
        o = Order.objects.create(branch=self.branch, total=0)
        events, max_id = orders_payload(self.company.id, None, 0)
        self.assertTrue(any(f'#{o.number}' in e for e in events))
        self.assertEqual(max_id, o.pk)

    def test_orders_payload_branch_scoped_and_cursor(self):
        from menu.dashboard.views import orders_payload
        o = Order.objects.create(branch=self.branch, total=0)
        # after_id at o.pk → nothing new
        events, _ = orders_payload(self.company.id, self.branch.id, o.pk)
        self.assertEqual(events, [])

    def test_stream_content_type(self):
        r = self.client.get('/dashboard/orders/stream/?once=1')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'text/event-stream')

    def test_branch_stream_forbidden_other_company(self):
        other = Company.objects.create(name='Other', slug='other')
        tok = set_current_company(other)
        try:
            fbranch = Branch.objects.create(company=other, name='Far', slug='far')
        finally:
            reset_current_company(tok)
        r = self.client.get(f'/dashboard/branch/{fbranch.slug}/orders/stream/?once=1')
        self.assertEqual(r.status_code, 403)
