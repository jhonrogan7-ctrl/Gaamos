import json

import pytest
from menu.models import Company, Branch, GuestSession, Order, Table, MenuItem
from menu.tenancy import set_current_company
from menu.guest_sessions import COOKIE
from menu.tests.base import TenantTestCase


@pytest.mark.django_db
def test_order_guest_session_attribution():
    """Test that an Order can be attributed to a GuestSession via related_name."""
    co = Company.objects.create(name="Cafe", slug="cafe")
    set_current_company(co)
    br = Branch.objects.create(company=co, name="Main", address="x")
    gs = GuestSession.objects.create(branch=br, token="t0001", label="Guest A")

    # Create an order with a guest session
    order = Order.objects.create(company=co, branch=br, guest_session=gs)

    # Test the reverse relation
    assert gs.orders.count() == 1
    assert gs.orders.first() == order


@pytest.mark.django_db
def test_order_without_guest_session():
    """Test that an Order can still allow guest_session to be None."""
    co = Company.objects.create(name="Cafe", slug="cafe")
    set_current_company(co)
    br = Branch.objects.create(company=co, name="Main", address="x")

    # Create an order without a guest session
    order = Order.objects.create(company=co, branch=br)

    # Test that guest_session can be None
    assert order.guest_session is None


class PlaceOrderGuestSessionTest(TenantTestCase):
    """place_order attaches the placed order to a browser-scoped guest session
    and sets the session cookie on the response (Task 1.5)."""

    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')
        self.item = MenuItem.objects.create(company=self.company, name='Latte', price=150)
        self.table = Table.objects.create(branch=self.branch, label='7', code='abc123')

    def _post(self, body):
        return self.client.post('/api/order/', data=json.dumps(body),
                                content_type='application/json')

    def test_order_attributed_to_new_guest_session_and_cookie_set(self):
        r = self._post({'branch': 'lake', 'table': 'abc123',
                        'items': [{'id': self.item.id, 'qty': 1}]})
        self.assertEqual(r.status_code, 200)
        self.assertIn(COOKIE, r.cookies)

        order = Order.objects.get(number=r.json()['number'])
        self.assertIsNotNone(order.guest_session)
        self.assertEqual(order.guest_session.label, 'Guest A')

    def test_second_order_with_cookie_reuses_same_session(self):
        r1 = self._post({'branch': 'lake', 'table': 'abc123',
                         'items': [{'id': self.item.id, 'qty': 1}]})
        order1 = Order.objects.get(number=r1.json()['number'])

        # The test client persists cookies from the response automatically,
        # so this second POST carries the gaamos_gs cookie set above.
        r2 = self._post({'branch': 'lake', 'table': 'abc123',
                         'items': [{'id': self.item.id, 'qty': 1}]})
        order2 = Order.objects.get(number=r2.json()['number'])

        self.assertEqual(order2.guest_session_id, order1.guest_session_id)
        self.assertEqual(order2.guest_session.label, 'Guest A')
        self.assertEqual(GuestSession.objects.filter(branch=self.branch, table=self.table).count(), 1)
