from urllib.parse import urlsplit, parse_qs

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase

from menu.impersonation import resolve_token
from menu.models import Company

APEX = settings.BASE_DOMAIN


class OpsImpersonateIssueTests(TestCase):
    def setUp(self):
        self.apex = {'HTTP_HOST': APEX}
        self.boss = User.objects.create_superuser('boss', 'b@x.io', 'pw')
        self.client.force_login(self.boss)
        self.co = Company.objects.create(name='Momo Ghar', slug='momoghar')

    def issue(self, company_id, **extra):
        return self.client.post(
            f'/platform/tenants/{company_id}/impersonate',
            **{**self.apex, **extra})

    def test_post_redirects_to_tenant_host_with_valid_token(self):
        resp = self.issue(self.co.id)
        self.assertEqual(resp.status_code, 302)
        parts = urlsplit(resp['Location'])
        self.assertEqual(parts.scheme, 'http')          # test client scheme
        self.assertEqual(parts.netloc, f'momoghar.{APEX}')
        self.assertEqual(parts.path, '/dashboard/impersonate/')
        token = parse_qs(parts.query)['token'][0]
        self.assertEqual(resolve_token(token, self.co), self.boss)

    def test_port_preserved_from_request_host(self):
        resp = self.issue(self.co.id, HTTP_HOST=f'{APEX}:8005')
        self.assertEqual(urlsplit(resp['Location']).netloc,
                         f'momoghar.{APEX}:8005')

    def test_get_is_405(self):
        resp = self.client.get(
            f'/platform/tenants/{self.co.id}/impersonate', **self.apex)
        self.assertEqual(resp.status_code, 405)

    def test_non_superuser_bounced_to_ops_login(self):
        plain = User.objects.create_user('plain', 'p@x.io', 'pw')
        self.client.force_login(plain)
        resp = self.issue(self.co.id)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/platform/login')

    def test_unknown_company_404(self):
        self.assertEqual(self.issue(99999).status_code, 404)

    def test_suspended_company_404(self):
        self.co.status = 'suspended'
        self.co.save(update_fields=['status'])
        self.assertEqual(self.issue(self.co.id).status_code, 404)
