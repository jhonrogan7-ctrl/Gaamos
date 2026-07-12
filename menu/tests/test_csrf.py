import json

from django.test import Client, override_settings
from django.contrib.auth import get_user_model

from menu.models import (
    Branch, Category, MenuItem, BranchCategory, BranchItemPlacement,
)
from menu.tests.base import TenantTestCase


@override_settings(ALLOWED_HOSTS=['.zxyn.online', 'testserver'])
class CsrfEnforcementTest(TenantTestCase):
    """CsrfViewMiddleware is installed: unsafe requests without a valid token are
    rejected (403), while the intended double-submit flows are accepted — the
    dashboard fetch POSTs (X-CSRFToken header read from the cookie by getCookie)
    and the public guest order POST."""

    def setUp(self):
        super().setUp()
        U = get_user_model()
        self.user = U.objects.create_user('mgr', password='pass')
        self.make_owner(self.user)
        self.branch = Branch.objects.create(company=self.company, name='Main', slug='main')
        self.cat = Category.objects.create(name='Drinks', slug='drinks', display_order=1)
        self.item = MenuItem.objects.create(company=self.company, name='Mango', slug='mango', price=100)
        BranchCategory.objects.create(branch=self.branch, category=self.cat)
        self.pl = BranchItemPlacement.objects.create(
            branch=self.branch, menu_item=self.item, category=self.cat)
        # enforce_csrf_checks => the client behaves like a real browser (token required).
        self.browser = Client(enforce_csrf_checks=True, HTTP_HOST=self.host)

    # ---- dashboard fetch POST (branch builder delete) ----
    def test_dashboard_post_without_token_rejected(self):
        self.browser.login(username='mgr', password='pass')
        r = self.browser.post(f'/dashboard/branch/main/placement/{self.pl.pk}/remove/')
        self.assertEqual(r.status_code, 403)
        self.assertTrue(BranchItemPlacement.objects.filter(pk=self.pl.pk).exists())

    def test_dashboard_post_with_header_token_accepted(self):
        self.browser.login(username='mgr', password='pass')
        # GET a dashboard page to receive the csrftoken cookie (base.html renders it).
        self.browser.get('/dashboard/branch/main/')
        token = self.browser.cookies['csrftoken'].value
        r = self.browser.post(f'/dashboard/branch/main/placement/{self.pl.pk}/remove/',
                              HTTP_X_CSRFTOKEN=token)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(BranchItemPlacement.objects.filter(pk=self.pl.pk).exists())

    # ---- public guest order POST ----
    def _order_body(self):
        return json.dumps({'branch': 'main', 'items': [{'id': self.item.pk, 'qty': 1}]})

    def test_guest_order_without_token_rejected(self):
        r = self.browser.post('/api/order/', data=self._order_body(),
                              content_type='application/json')
        self.assertEqual(r.status_code, 403)

    def test_guest_order_with_header_token_accepted(self):
        self.browser.get('/')  # root() @ensure_csrf_cookie sets the token cookie
        token = self.browser.cookies['csrftoken'].value
        r = self.browser.post('/api/order/', data=self._order_body(),
                              content_type='application/json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get('ok'))
