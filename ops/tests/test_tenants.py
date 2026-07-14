import re

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase

from menu.models import Branch, Company, Membership

APEX = settings.BASE_DOMAIN


class OpsTenantsTests(TestCase):
    def setUp(self):
        self.apex = {'HTTP_HOST': APEX}
        boss = User.objects.create_superuser('boss', 'b@x.io', 'pw')
        self.client.force_login(boss)
        self.co = Company.objects.create(name='Momo Ghar', slug='momoghar',
                                         package='vip')
        self.owner = User.objects.create_user('momo-owner', 'o@x.np', 'old-pass')
        Membership.objects.create(user=self.owner, company=self.co,
                                  role=Membership.ROLE_OWNER)

    def test_list_shows_company_package_and_link(self):
        resp = self.client.get('/platform/tenants', **self.apex)
        self.assertContains(resp, 'Momo Ghar')
        self.assertContains(resp, f'momoghar.{APEX}')
        self.assertContains(resp, 'ops-chip vip')

    def test_toggle_suspends_and_guest_404s(self):
        Branch.all_objects.create(company=self.co, name='Main', address='KTM',
                                  slug='main')
        resp = self.client.post(f'/platform/tenants/{self.co.id}/toggle',
                                **self.apex)
        self.assertEqual(resp.status_code, 302)
        self.co.refresh_from_db()
        self.assertEqual(self.co.status, 'suspended')
        # LocaleMiddleware first bounces / to /en/ (it rewrites the tenant 404);
        # the language-prefixed request then 404s — follow to the final status.
        guest = self.client.get('/', HTTP_HOST=f'momoghar.{APEX}', follow=True)
        self.assertEqual(guest.status_code, 404)
        self.client.post(f'/platform/tenants/{self.co.id}/toggle', **self.apex)
        self.co.refresh_from_db()
        self.assertEqual(self.co.status, 'active')

    def test_reset_owner_password_shows_once_and_works(self):
        resp = self.client.post(
            f'/platform/tenants/{self.co.id}/reset-password',
            follow=True, **self.apex)
        body = resp.content.decode()
        self.assertIn('momo-owner', body)
        m = re.search(r'data-onetime-password="([^"]+)"', body)
        self.assertIsNotNone(m)
        new_pw = m.group(1)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password(new_pw))
        self.assertFalse(self.owner.check_password('old-pass'))
        again = self.client.get('/platform/tenants', **self.apex)
        self.assertNotIn('data-onetime-password', again.content.decode())

    def test_reset_password_without_owner_is_400(self):
        bare = Company.objects.create(name='No Owner', slug='noowner')
        resp = self.client.post(
            f'/platform/tenants/{bare.id}/reset-password', **self.apex)
        self.assertEqual(resp.status_code, 400)
