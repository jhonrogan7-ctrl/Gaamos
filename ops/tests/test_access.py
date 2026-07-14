from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase

from menu.models import Company

APEX = settings.BASE_DOMAIN


class PlatformAccessTests(TestCase):
    def setUp(self):
        self.apex = {'HTTP_HOST': APEX}
        self.superuser = User.objects.create_superuser('boss', 'b@x.io', 'pw-boss-1')
        self.pleb = User.objects.create_user('pleb', 'p@x.io', 'pw-pleb-1')

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get('/platform/leads', **self.apex)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/platform/login', resp['Location'])

    def test_non_superuser_login_rejected_generic(self):
        resp = self.client.post('/platform/login',
                                {'username': 'pleb', 'password': 'pw-pleb-1'},
                                **self.apex)
        self.assertContains(resp, 'Invalid credentials', status_code=200)

    def test_non_superuser_session_still_blocked(self):
        self.client.force_login(self.pleb)
        resp = self.client.get('/platform/leads', **self.apex)
        self.assertEqual(resp.status_code, 302)

    def test_superuser_logs_in_and_sees_panel(self):
        resp = self.client.post('/platform/login',
                                {'username': 'boss', 'password': 'pw-boss-1'},
                                follow=True, **self.apex)
        self.assertContains(resp, 'Leads')

    def test_tenant_host_404s(self):
        Company.objects.create(name='T', slug='tenantco')
        self.client.force_login(self.superuser)
        resp = self.client.get('/platform/leads',
                               HTTP_HOST=f'tenantco.{APEX}')
        self.assertEqual(resp.status_code, 404)

    def test_login_on_tenant_host_404s(self):
        Company.objects.create(name='T', slug='tenantco')
        resp = self.client.get('/platform/login',
                               HTTP_HOST=f'tenantco.{APEX}')
        self.assertEqual(resp.status_code, 404)

    def test_logout_requires_post_and_works(self):
        self.client.force_login(self.superuser)
        resp = self.client.post('/platform/logout', **self.apex)
        self.assertEqual(resp.status_code, 302)
        resp = self.client.get('/platform/leads', **self.apex)
        self.assertEqual(resp.status_code, 302)
