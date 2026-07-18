from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User

from menu.impersonation import make_token, resolve_token
from menu.models import Company
from menu.tests.base import TenantTestCase


class TokenHelperTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser('boss', 'b@x.io', 'pw')

    def test_round_trip_resolves_admin(self):
        token = make_token(self.admin, self.company)
        self.assertEqual(resolve_token(token, self.company), self.admin)

    def test_token_is_single_use(self):
        token = make_token(self.admin, self.company)
        self.assertEqual(resolve_token(token, self.company), self.admin)
        self.assertIsNone(resolve_token(token, self.company))

    def test_wrong_company_rejected(self):
        other = Company.objects.create(name='Other Co', slug='otherco')
        token = make_token(self.admin, other)
        self.assertIsNone(resolve_token(token, self.company))
        # and the nonce was NOT burned by the failed attempt on the wrong host
        self.assertEqual(resolve_token(token, other), self.admin)

    def test_none_company_rejected(self):
        token = make_token(self.admin, self.company)
        self.assertIsNone(resolve_token(token, None))

    def test_tampered_token_rejected(self):
        token = make_token(self.admin, self.company)
        self.assertIsNone(resolve_token(token[:-2] + 'zz', self.company))

    def test_garbage_token_rejected(self):
        self.assertIsNone(resolve_token('not-a-token', self.company))
        self.assertIsNone(resolve_token('', self.company))

    def test_expired_token_rejected(self):
        token = make_token(self.admin, self.company)
        with mock.patch('menu.impersonation.MAX_AGE', -1):
            self.assertIsNone(resolve_token(token, self.company))

    def test_non_superuser_target_rejected(self):
        plain = User.objects.create_user('plain', 'p@x.io', 'pw')
        token = make_token(plain, self.company)
        self.assertIsNone(resolve_token(token, self.company))

    def test_inactive_superuser_rejected(self):
        self.admin.is_active = False
        self.admin.save(update_fields=['is_active'])
        token = make_token(self.admin, self.company)
        self.assertIsNone(resolve_token(token, self.company))


class ImpersonateConsumeTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser('boss', 'b@x.io', 'pw')

    def consume(self, token):
        return self.client.get('/dashboard/impersonate/', {'token': token})

    def test_valid_token_logs_in_and_redirects_home(self):
        resp = self.consume(make_token(self.admin, self.company))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/dashboard/')
        self.assertEqual(int(self.client.session['_auth_user_id']),
                         self.admin.pk)

    def test_missing_or_garbage_token_404(self):
        self.assertEqual(
            self.client.get('/dashboard/impersonate/').status_code, 404)
        self.assertEqual(self.consume('garbage').status_code, 404)

    def test_replay_404(self):
        token = make_token(self.admin, self.company)
        self.assertEqual(self.consume(token).status_code, 302)
        self.client.post('/dashboard/logout/')
        self.assertEqual(self.consume(token).status_code, 404)

    def test_wrong_company_token_404(self):
        other = Company.objects.create(name='Other Co', slug='otherco')
        token = make_token(self.admin, other)
        self.assertEqual(self.consume(token).status_code, 404)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_expired_token_404(self):
        token = make_token(self.admin, self.company)
        with mock.patch('menu.impersonation.MAX_AGE', -1):
            self.assertEqual(self.consume(token).status_code, 404)

    def test_non_superuser_target_404(self):
        plain = User.objects.create_user('plain', 'p@x.io', 'pw')
        token = make_token(plain, self.company)
        self.assertEqual(self.consume(token).status_code, 404)

    def test_session_key_rotated_on_login(self):
        self.client.get('/dashboard/login/')          # establish a session
        before = self.client.session.session_key
        self.consume(make_token(self.admin, self.company))
        self.assertNotEqual(self.client.session.session_key, before)


class BannerAndExitTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser('boss', 'b@x.io', 'pw')

    def test_superuser_sees_banner_and_exit_on_dashboard(self):
        self.client.force_login(self.admin)
        resp = self.client.get('/dashboard/')
        self.assertContains(resp, 'imp-bar')
        self.assertContains(resp, 'Platform admin')
        self.assertContains(resp, 'Test Co')            # company name in text
        self.assertContains(resp, '/dashboard/impersonate/exit/')

    def test_owner_and_manager_do_not_see_banner(self):
        owner = User.objects.create_user('owner', 'o@x.io', 'pass')
        self.make_owner(owner)
        self.client.force_login(owner)
        self.assertNotContains(self.client.get('/dashboard/'), 'imp-bar')

        mgr = User.objects.create_user('mgr', 'm@x.io', 'pass')
        self.make_manager(mgr)
        self.client.force_login(mgr)
        self.assertNotContains(self.client.get('/dashboard/'), 'imp-bar')

    def test_exit_logs_out_and_redirects_to_apex_ops(self):
        self.client.force_login(self.admin)
        resp = self.client.post('/dashboard/impersonate/exit/')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'],
                         f'http://{settings.BASE_DOMAIN}/platform/tenants')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_exit_get_405_and_anonymous_404(self):
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.get('/dashboard/impersonate/exit/').status_code, 405)
        self.client.post('/dashboard/logout/')
        self.assertEqual(
            self.client.post('/dashboard/impersonate/exit/').status_code, 404)

    def test_imp_bar_rule_survives_the_tailwind_build(self):
        from pathlib import Path
        css = (Path(settings.BASE_DIR) / 'static/css/app.css').read_text()
        self.assertRegex(css, r'[}{]\.imp-bar\{')
