from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase

from core.models import Lead
from menu.models import Branch, Company, Membership

APEX = settings.BASE_DOMAIN

FORM = {
    'name': 'Momo Ghar', 'slug': 'momoghar', 'tagline': 'Best momo in Thamel',
    'phone': '9800000000', 'email': 'hi@momoghar.np',
    'instagram': '', 'facebook': '', 'tiktok': '',
    'menu_theme': 'berry', 'menu_layout': 'tabs',
    'package': 'vip', 'status': 'active',
    'owner_username': 'momo-owner', 'owner_email': 'o@momoghar.np',
    'owner_password': '',   # blank → auto-generate
    'branch_name': 'Thamel', 'branch_address': 'Mandala Street, KTM',
}


class OpsCreateTenantTests(TestCase):
    def setUp(self):
        self.apex = {'HTTP_HOST': APEX}
        boss = User.objects.create_superuser('boss', 'b@x.io', 'pw')
        self.client.force_login(boss)

    def test_happy_path_creates_everything(self):
        lead = Lead.objects.create(name='Sita', venue_name='Momo Ghar',
                                   phone='98', email='s@x.np')
        resp = self.client.post(f'/platform/tenants/new?lead={lead.id}',
                                FORM, follow=True, **self.apex)
        self.assertEqual(resp.status_code, 200)
        co = Company.objects.get(slug='momoghar')
        self.assertEqual(co.package, 'vip')
        self.assertEqual(co.menu_theme, 'berry')
        self.assertEqual(co.menu_layout, 'tabs')
        branch = Branch.all_objects.get(company=co)
        self.assertEqual(branch.name, 'Thamel')
        self.assertTrue(branch.qr_image)          # QR generated
        m = Membership.objects.get(company=co)
        self.assertEqual(m.role, Membership.ROLE_OWNER)
        self.assertEqual(m.user.username, 'momo-owner')
        lead.refresh_from_db()
        self.assertEqual(lead.status, 'converted')
        self.assertEqual(lead.company, co)
        body = resp.content.decode()
        self.assertIn(f'momoghar.{APEX}', body)
        self.assertIn('data-onetime-password=', body)

    def test_duplicate_slug_is_form_error(self):
        Company.objects.create(name='X', slug='momoghar')
        resp = self.client.post('/platform/tenants/new', FORM, **self.apex)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already taken')
        self.assertEqual(Company.objects.filter(name='Momo Ghar').count(), 0)

    def test_duplicate_username_is_form_error(self):
        User.objects.create_user('momo-owner')
        resp = self.client.post('/platform/tenants/new', FORM, **self.apex)
        self.assertContains(resp, 'username is already taken')
        self.assertFalse(Company.objects.filter(slug='momoghar').exists())

    def test_reserved_slug_is_form_error(self):
        bad = dict(FORM, slug='platform')
        resp = self.client.post('/platform/tenants/new', bad, **self.apex)
        self.assertContains(resp, 'reserved')

    def test_prefill_from_lead(self):
        lead = Lead.objects.create(name='Sita', venue_name='Momo Ghar',
                                   phone='9812345678', email='s@x.np')
        resp = self.client.get(f'/platform/tenants/new?lead={lead.id}',
                               **self.apex)
        self.assertContains(resp, 'value="Momo Ghar"')
        self.assertContains(resp, 'value="9812345678"')

    def test_typed_password_is_used(self):
        form = dict(FORM, owner_password='chosen-by-founder-9')
        self.client.post('/platform/tenants/new', form, **self.apex)
        user = User.objects.get(username='momo-owner')
        self.assertTrue(user.check_password('chosen-by-founder-9'))

    def test_credentials_shown_once_only(self):
        resp = self.client.post('/platform/tenants/new', FORM, follow=True,
                                **self.apex)
        self.assertIn('data-onetime-password=', resp.content.decode())
        co = Company.objects.get(slug='momoghar')
        again = self.client.get(f'/platform/tenants/{co.id}/created',
                                **self.apex)
        self.assertNotIn('data-onetime-password=', again.content.decode())
