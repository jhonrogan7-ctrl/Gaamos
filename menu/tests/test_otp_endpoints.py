import json
from unittest.mock import patch

from django.conf import settings

from menu.guest_sessions import COOKIE
from menu.models import Branch, GuestSession, OtpChallenge
from menu.otp import issue_code
from menu.tests.base import TenantTestCase


class IdentityOtpEndpointsTest(TenantTestCase):
    """Guest identity + OTP endpoints (Task 2.3): identity_submit, otp_verify,
    otp_resend. All resolve the active GuestSession from the gaamos_gs cookie."""

    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')
        self.session = GuestSession.objects.create(
            company=self.company, branch=self.branch, token='tok123', label='Guest A')
        self.client.cookies[COOKIE] = self.session.token

    def _post(self, path, body, **extra):
        return self.client.post(path, data=json.dumps(body),
                                 content_type='application/json', **extra)

    # -- identity_submit: name/room mode (no OTP) --

    def test_identity_submit_name_mode_sets_name_no_otp(self):
        self.company.identity_mode = 'name'
        self.company.save()
        r = self._post('/api/identity/', {'name': 'Rita'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {'ok': True})
        self.session.refresh_from_db()
        self.assertEqual(self.session.name, 'Rita')
        self.assertFalse(OtpChallenge.objects.filter(session=self.session).exists())

    def test_identity_submit_room_mode_sets_name_and_contact_no_otp(self):
        self.company.identity_mode = 'room'
        self.company.save()
        r = self._post('/api/identity/', {'name': 'Rita', 'phone': '204'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {'ok': True})
        self.session.refresh_from_db()
        self.assertEqual(self.session.name, 'Rita')
        self.assertEqual(self.session.contact, '204')
        self.assertFalse(OtpChallenge.objects.filter(session=self.session).exists())

    # -- identity_submit: phone mode (OTP) --

    @patch('menu.tasks.send_otp_sms.delay')
    def test_identity_submit_phone_mode_issues_code_and_enqueues_sms(self, delay):
        self.company.identity_mode = 'phone'
        self.company.save()
        r = self._post('/api/identity/', {'name': 'Rita', 'phone': '9800000000'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {'ok': True, 'otp': True})
        self.assertTrue(
            OtpChallenge.objects.filter(session=self.session, phone='9800000000').exists())
        self.assertTrue(delay.called)

    def test_identity_submit_phone_mode_missing_phone_400(self):
        self.company.identity_mode = 'phone'
        self.company.save()
        r = self._post('/api/identity/', {'name': 'Rita'})
        self.assertEqual(r.status_code, 400)

    # -- identity_submit: cookie resolution --

    def test_identity_submit_no_cookie_returns_400(self):
        self.client.cookies.pop(COOKIE, None)
        r = self._post('/api/identity/', {'name': 'Rita'})
        self.assertEqual(r.status_code, 400)

    def test_identity_submit_invalid_cookie_returns_400(self):
        self.client.cookies[COOKIE] = 'does-not-exist'
        r = self._post('/api/identity/', {'name': 'Rita'})
        self.assertEqual(r.status_code, 400)

    # -- otp_verify --

    def test_otp_verify_wrong_code_returns_false(self):
        issue_code(self.session, '9800000000')
        r = self._post('/api/otp/verify/', {'code': '0000'})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertFalse(data['ok'])
        self.session.refresh_from_db()
        self.assertFalse(self.session.verified)

    def test_otp_verify_right_code_returns_true_and_verified(self):
        code = issue_code(self.session, '9800000000')
        r = self._post('/api/otp/verify/', {'code': code})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {'ok': True, 'verified': True})

    def test_otp_verify_no_cookie_returns_400(self):
        self.client.cookies.pop(COOKIE, None)
        r = self._post('/api/otp/verify/', {'code': '1234'})
        self.assertEqual(r.status_code, 400)

    def test_otp_verify_invalid_cookie_returns_400(self):
        self.client.cookies[COOKIE] = 'does-not-exist'
        r = self._post('/api/otp/verify/', {'code': '1234'})
        self.assertEqual(r.status_code, 400)

    # -- otp_resend --

    @patch('menu.tasks.send_otp_sms.delay')
    def test_otp_resend_reissues_code_and_enqueues_sms(self, delay):
        issue_code(self.session, '9800000000')
        r = self._post('/api/otp/resend/', {})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {'ok': True})
        self.assertEqual(OtpChallenge.objects.filter(session=self.session).count(), 2)
        self.assertTrue(delay.called)

    def test_otp_resend_no_cookie_returns_400(self):
        self.client.cookies.pop(COOKIE, None)
        r = self._post('/api/otp/resend/', {})
        self.assertEqual(r.status_code, 400)

    def test_otp_resend_invalid_cookie_returns_400(self):
        self.client.cookies[COOKIE] = 'does-not-exist'
        r = self._post('/api/otp/resend/', {})
        self.assertEqual(r.status_code, 400)

    # -- no tenant context (apex/reserved/unknown host): 400, never 500 --

    def test_identity_submit_non_empty_cookie_no_tenant_context_returns_400_not_500(self):
        # TenantMiddleware sets request.company = None on the apex host (no
        # subdomain label to resolve). The gaamos_gs cookie is still present
        # and valid for the tenant that issued it — this must 400, not 500.
        r = self._post('/api/identity/', {'name': 'Rita'}, HTTP_HOST=settings.BASE_DOMAIN)
        self.assertEqual(r.status_code, 400)

    def test_otp_verify_non_empty_cookie_no_tenant_context_returns_400_not_500(self):
        r = self._post('/api/otp/verify/', {'code': '1234'}, HTTP_HOST=settings.BASE_DOMAIN)
        self.assertEqual(r.status_code, 400)

    def test_otp_resend_non_empty_cookie_no_tenant_context_returns_400_not_500(self):
        r = self._post('/api/otp/resend/', {}, HTTP_HOST=settings.BASE_DOMAIN)
        self.assertEqual(r.status_code, 400)
