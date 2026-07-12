"""PWA wiring on tenant hosts: guest menu and dashboard are separately
installable apps (distinct manifest ids) and both register /sw.js."""
from django.contrib.auth import get_user_model

from menu.tests.base import TenantTestCase


class GuestPwaTest(TenantTestCase):
    def test_guest_menu_links_guest_manifest_and_registers_sw(self):
        body = self.client.get('/').content.decode()
        self.assertIn('rel="manifest"', body)
        self.assertIn('pwa/manifest.webmanifest', body)
        self.assertNotIn('manifest-dashboard', body)
        self.assertIn('serviceWorker', body)
        self.assertIn('apple-touch-icon', body)


class DashboardPwaTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        U = get_user_model()
        self.owner = U.objects.create_user('boss', password='pass')
        self.make_owner(self.owner)
        self.login_as(self.owner)

    def test_dashboard_links_dashboard_manifest_and_registers_sw(self):
        body = self.client.get('/dashboard/overview/').content.decode()
        self.assertIn('pwa/manifest-dashboard.webmanifest', body)
        self.assertIn('serviceWorker', body)
        self.assertIn('apple-touch-icon', body)
