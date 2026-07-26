"""Web Push notifications for new orders.

Network-free by construction: every test either patches `pywebpush.webpush` or
exercises pure resolution logic. Nothing here may make an outbound request.

The load-bearing test in this file is recipient scoping — a branch manager must
never be notified about another branch's trade, since a notification carries the
order's table and total onto their lock screen.
"""
import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import override_settings

from menu.models import (
    Branch, MenuItem, Membership, Order, OrderItem, PushSubscription,
)
from menu import push
from menu.tests.base import TenantTestCase

VAPID = {
    'VAPID_PUBLIC_KEY': 'test-public-key',
    'VAPID_PRIVATE_KEY': 'test-private-key',
    'VAPID_ADMIN_EMAIL': 'admin@example.com',
}


class _Resp:
    def __init__(self, status_code):
        self.status_code = status_code


class PushRecipientScopingTest(TenantTestCase):
    """Who gets told about an order. Mirrors visible_branches()."""

    def setUp(self):
        super().setUp()
        self.a = Branch.objects.create(company=self.company, name='A', slug='a')
        self.b = Branch.objects.create(company=self.company, name='B', slug='b')
        self.owner = User.objects.create_user('owner', password='pass')
        self.make_owner(self.owner)
        self.mgr_a = User.objects.create_user('mgr_a', password='pass')
        self.make_manager(self.mgr_a, branches=[self.a])
        self.mgr_b = User.objects.create_user('mgr_b', password='pass')
        self.make_manager(self.mgr_b, branches=[self.b])

    def test_owner_is_notified_about_any_branch(self):
        order = Order.objects.create(branch=self.b, total=100)
        self.assertIn(self.owner.pk, push.recipients_for_order(order))

    def test_manager_notified_about_their_own_branch(self):
        order = Order.objects.create(branch=self.a, total=100)
        self.assertIn(self.mgr_a.pk, push.recipients_for_order(order))

    def test_manager_not_notified_about_another_branch(self):
        # The whole point: a lock-screen notification would leak B's table and
        # takings to someone the dashboard refuses to show B to.
        order = Order.objects.create(branch=self.b, total=9999)
        self.assertNotIn(self.mgr_a.pk, push.recipients_for_order(order))

    def test_resolution_works_with_no_tenant_context(self):
        """The Celery worker has no company in context.

        Regression: `prefetch_related('branches')` walked Branch's fail-closed
        manager and raised TenantContextRequired in the worker, while every
        test passed — TenantTestCase always has context set. This test drops
        the context to reproduce what the worker actually does.
        """
        from menu.tenancy import get_current_company, reset_current_company, set_current_company

        order = Order.objects.create(branch=self.a, total=100)
        order_id, branch_id = order.pk, order.branch_id

        token = set_current_company(None)
        try:
            self.assertIsNone(get_current_company())
            fresh = Order.all_objects.get(pk=order_id)
            ids = push.recipients_for_order(fresh)       # must not raise
        finally:
            reset_current_company(token)

        self.assertEqual(branch_id, self.a.pk)
        self.assertIn(self.owner.pk, ids)
        self.assertIn(self.mgr_a.pk, ids)
        self.assertNotIn(self.mgr_b.pk, ids)

    def test_no_duplicate_when_a_user_matches_twice(self):
        order = Order.objects.create(branch=self.a, total=100)
        ids = push.recipients_for_order(order)
        self.assertEqual(len(ids), len(set(ids)))

    def test_other_companys_staff_never_notified(self):
        from menu.models import Company
        from menu.tenancy import set_current_company, reset_current_company
        other = Company.objects.create(name='Other', slug='other-co')
        stranger = User.objects.create_user('stranger', password='pass')
        Membership.objects.create(user=stranger, company=other,
                                  role=Membership.ROLE_OWNER)
        order = Order.objects.create(branch=self.a, total=100)
        self.assertNotIn(stranger.pk, push.recipients_for_order(order))


@override_settings(**VAPID)
class PushSendingTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(company=self.company, name='A', slug='a')
        self.owner = User.objects.create_user('owner', password='pass')
        self.make_owner(self.owner)
        self.sub = PushSubscription.objects.create(
            company=self.company, user=self.owner,
            endpoint='https://push.example.com/abc',
            p256dh='key', auth='auth')
        self.order = Order.objects.create(branch=self.branch, total=600,
                                          table_label='7')
        item = MenuItem.objects.create(company=self.company, name='Latte',
                                       slug='latte', price=300)
        OrderItem.objects.create(order=self.order, menu_item=item, name='Latte',
                                 unit_price=300, qty=2)

    def test_payload_names_the_table_and_total(self):
        p = push.order_payload(self.order)
        self.assertIn('Table 7', p['title'])
        self.assertIn('Rs 600', p['body'])
        self.assertIn('2 items', p['body'])
        self.assertEqual(p['url'], '/dashboard/orders/')

    def test_takeaway_order_says_takeaway(self):
        o = Order.objects.create(branch=self.branch, total=100)
        self.assertIn('Takeaway', push.order_payload(o)['title'])

    def test_single_item_is_not_pluralised(self):
        o = Order.objects.create(branch=self.branch, total=300)
        OrderItem.objects.create(order=o, name='Latte', unit_price=300, qty=1)
        self.assertIn('1 item ', push.order_payload(o)['body'] + ' ')

    def test_sends_one_push_per_subscription(self):
        with patch('pywebpush.webpush') as wp:
            tally = push.notify_new_order(self.order)
        self.assertEqual(tally, {'sent': 1, 'failed': 0, 'dropped': 0})
        self.assertEqual(wp.call_count, 1)
        payload = json.loads(wp.call_args.kwargs['data'])
        self.assertIn('Table 7', payload['title'])

    def test_expired_subscription_is_deleted(self):
        # 404/410 is the push service saying the registration is gone. Keeping
        # it would mean retrying a dead endpoint on every future order.
        from pywebpush import WebPushException
        exc = WebPushException('gone')
        exc.response = _Resp(410)
        with patch('pywebpush.webpush', side_effect=exc):
            tally = push.notify_new_order(self.order)
        self.assertEqual(tally, {'sent': 0, 'failed': 0, 'dropped': 1})
        self.assertFalse(PushSubscription.all_objects.filter(pk=self.sub.pk).exists())

    def test_transient_failure_keeps_the_subscription(self):
        # A push service outage must not silently unsubscribe every venue.
        from pywebpush import WebPushException
        exc = WebPushException('boom')
        exc.response = _Resp(503)
        with patch('pywebpush.webpush', side_effect=exc):
            tally = push.notify_new_order(self.order)
        # Reported as failed, NOT as sent: an outage must not look healthy.
        self.assertEqual(tally, {'sent': 0, 'failed': 1, 'dropped': 0})
        self.assertTrue(PushSubscription.all_objects.filter(pk=self.sub.pk).exists())

    def test_unexpected_error_does_not_propagate(self):
        with patch('pywebpush.webpush', side_effect=RuntimeError('kaboom')):
            tally = push.notify_new_order(self.order)           # must not raise
        self.assertEqual(tally, {'sent': 0, 'failed': 1, 'dropped': 0})

    def test_manager_of_another_branch_gets_no_push(self):
        other = Branch.objects.create(company=self.company, name='B', slug='b')
        mgr = User.objects.create_user('mgr_b', password='pass')
        self.make_manager(mgr, branches=[other])
        PushSubscription.objects.create(
            company=self.company, user=mgr,
            endpoint='https://push.example.com/other', p256dh='k', auth='a')
        with patch('pywebpush.webpush') as wp:
            push.notify_new_order(self.order)
        # Only the owner's subscription, never the other branch's manager.
        self.assertEqual(wp.call_count, 1)
        self.assertEqual(wp.call_args.kwargs['subscription_info']['endpoint'],
                         'https://push.example.com/abc')


class PushDisabledTest(TenantTestCase):
    @override_settings(VAPID_PUBLIC_KEY='', VAPID_PRIVATE_KEY='')
    def test_no_keys_means_no_send_and_no_error(self):
        # A deployment that never configured push must still take orders.
        branch = Branch.objects.create(company=self.company, name='A', slug='a')
        order = Order.objects.create(branch=branch, total=100)
        self.assertFalse(push.push_enabled())
        with patch('pywebpush.webpush') as wp:
            self.assertEqual(push.notify_new_order(order),
                             {'sent': 0, 'failed': 0, 'dropped': 0})
        wp.assert_not_called()


@override_settings(**VAPID)
class PushSubscribeEndpointTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('boss', password='pass')
        self.make_owner(self.user)
        self.login_as(self.user)

    def _sub(self, endpoint='https://push.example.com/x'):
        return {'endpoint': endpoint, 'keys': {'p256dh': 'pk', 'auth': 'au'}}

    def _post(self, url, body):
        return self.client.post(url, data=json.dumps(body),
                                content_type='application/json')

    def test_subscribe_stores_the_registration(self):
        r = self._post('/dashboard/push/subscribe/', self._sub())
        self.assertEqual(r.status_code, 200)
        s = PushSubscription.objects.get()
        self.assertEqual(s.user, self.user)
        self.assertEqual(s.company, self.company)
        self.assertEqual(s.p256dh, 'pk')

    def test_resubscribing_same_browser_updates_not_duplicates(self):
        # Toggling off and on again must not make the device notified twice.
        self._post('/dashboard/push/subscribe/', self._sub())
        body = self._sub()
        body['keys']['p256dh'] = 'rotated'
        self._post('/dashboard/push/subscribe/', body)
        self.assertEqual(PushSubscription.objects.count(), 1)
        self.assertEqual(PushSubscription.objects.get().p256dh, 'rotated')

    def test_malformed_body_is_rejected(self):
        r = self._post('/dashboard/push/subscribe/', {'nope': 1})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(PushSubscription.objects.count(), 0)

    def test_unsubscribe_removes_it(self):
        self._post('/dashboard/push/subscribe/', self._sub())
        r = self._post('/dashboard/push/unsubscribe/',
                       {'endpoint': 'https://push.example.com/x'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(PushSubscription.objects.count(), 0)

    def test_anonymous_cannot_subscribe(self):
        self.client.logout()
        r = self._post('/dashboard/push/subscribe/', self._sub())
        self.assertIn(r.status_code, (302, 403))
        self.assertEqual(PushSubscription.all_objects.count(), 0)

    def test_user_cannot_unsubscribe_someone_elses_endpoint(self):
        other = User.objects.create_user('other', password='pass')
        self.make_manager(other)
        PushSubscription.objects.create(
            company=self.company, user=other,
            endpoint='https://push.example.com/theirs', p256dh='k', auth='a')
        self._post('/dashboard/push/unsubscribe/',
                   {'endpoint': 'https://push.example.com/theirs'})
        self.assertTrue(PushSubscription.all_objects.filter(
            endpoint='https://push.example.com/theirs').exists())


class PlaceOrderQueuesPushTest(TenantTestCase):
    """The guest-facing order endpoint must hand off to the worker, and must
    survive that hand-off failing."""

    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(company=self.company, name='A', slug='a')
        self.item = MenuItem.objects.create(company=self.company, name='Latte',
                                            slug='latte', price=150)

    def _place(self):
        return self.client.post('/api/order/', data=json.dumps(
            {'branch': 'a', 'items': [{'id': self.item.id, 'qty': 1}]}),
            content_type='application/json')

    def test_placing_an_order_queues_a_push(self):
        with patch('menu.tasks.send_order_push.delay') as delay:
            r = self._place()
        self.assertEqual(r.status_code, 200)
        delay.assert_called_once()
        self.assertEqual(delay.call_args.args[0], Order.objects.get().pk)

    def test_order_still_succeeds_when_the_broker_is_down(self):
        # Celery unreachable must never turn a guest's paid order into an error.
        with patch('menu.tasks.send_order_push.delay',
                   side_effect=OSError('no broker')):
            r = self._place()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])
        self.assertEqual(Order.objects.count(), 1)


@override_settings(**VAPID)
class SendOrderPushTaskTest(TenantTestCase):
    def test_task_sends_for_a_real_order(self):
        from menu.tasks import send_order_push
        branch = Branch.objects.create(company=self.company, name='A', slug='a')
        owner = User.objects.create_user('owner', password='pass')
        self.make_owner(owner)
        PushSubscription.objects.create(
            company=self.company, user=owner,
            endpoint='https://push.example.com/z', p256dh='k', auth='a')
        order = Order.objects.create(branch=branch, total=100)
        with patch('pywebpush.webpush') as wp:
            result = send_order_push(order.pk)
        self.assertEqual(wp.call_count, 1)
        self.assertIn('sent=1', result)

    def test_task_on_a_deleted_order_is_a_noop(self):
        from menu.tasks import send_order_push
        self.assertEqual(send_order_push(999999), 'gone')


@override_settings(**VAPID)
class VapidKeyRotationTest(TenantTestCase):
    """Rotating the VAPID keypair must self-heal, not silently orphan devices.

    A subscription made against an old public key can never receive again — the
    push service rejects our signature with 401/403. If we treated that as a
    transient error we would retry it forever and the staff member's phone would
    stay quiet with no route back.
    """

    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(company=self.company, name='A', slug='a')
        self.owner = User.objects.create_user('owner', password='pass')
        self.make_owner(self.owner)
        self.sub = PushSubscription.objects.create(
            company=self.company, user=self.owner,
            endpoint='https://push.example.com/old-key', p256dh='k', auth='a')
        self.order = Order.objects.create(branch=self.branch, total=100)

    def _fail_with(self, status):
        from pywebpush import WebPushException
        exc = WebPushException('rejected')
        exc.response = _Resp(status)
        with patch('pywebpush.webpush', side_effect=exc):
            return push.notify_new_order(self.order)

    def test_403_drops_the_subscription_so_the_browser_re_registers(self):
        tally = self._fail_with(403)
        self.assertEqual(tally, {'sent': 0, 'failed': 0, 'dropped': 1})
        self.assertFalse(PushSubscription.all_objects.filter(pk=self.sub.pk).exists())

    def test_401_is_treated_the_same(self):
        self._fail_with(401)
        self.assertFalse(PushSubscription.all_objects.filter(pk=self.sub.pk).exists())

    def test_a_real_outage_is_still_not_treated_as_a_key_problem(self):
        # 503 must keep the subscription — otherwise one bad afternoon at the
        # push service would unsubscribe every venue.
        tally = self._fail_with(503)
        self.assertEqual(tally, {'sent': 0, 'failed': 1, 'dropped': 0})
        self.assertTrue(PushSubscription.all_objects.filter(pk=self.sub.pk).exists())


@override_settings(**VAPID)
class PushKeyEndpointTest(TenantTestCase):
    """The service worker fetches the current key here when the browser rotates
    a subscription on its own."""

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('boss', password='pass')
        self.make_owner(self.user)

    def test_serves_the_current_public_key(self):
        self.login_as(self.user)
        r = self.client.get('/dashboard/push/key/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['key'], 'test-public-key')

    def test_requires_membership(self):
        r = self.client.get('/dashboard/push/key/')
        self.assertIn(r.status_code, (302, 403))
