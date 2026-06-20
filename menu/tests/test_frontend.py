from pathlib import Path
from django.conf import settings
from django.test import SimpleTestCase
from django.contrib.auth import get_user_model
from menu.tests.base import TenantTestCase


class CssBuildTest(SimpleTestCase):
    def test_app_css_built_and_nonempty(self):
        css = Path(settings.BASE_DIR) / 'static' / 'css' / 'app.css'
        self.assertTrue(css.exists(), 'app.css not built — run bin/build-css.sh')
        self.assertGreater(css.stat().st_size, 1000, 'app.css suspiciously small')


class CssComponentsTest(SimpleTestCase):
    def _css(self):
        from pathlib import Path
        from django.conf import settings
        return (Path(settings.BASE_DIR) / 'static/css/app.css').read_text()

    def test_core_component_classes_present(self):
        css = self._css()
        for sel in ['.btn', '.panel', '.side', '.nav', '.tbl', '.stat', '.focal']:
            self.assertIn(sel, css, f'missing component class {sel}')


class DashboardShellTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        U = get_user_model()
        self.owner = U.objects.create_user('boss', password='pass')
        self.make_owner(self.owner)

    def test_shell_rebranded_and_sidebar(self):
        self.login_as(self.owner)
        r = self.client.get('/dashboard/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('Gaamos', body)
        self.assertNotIn('QR Manu', body)
        self.assertIn('class="side"', body)     # sidebar present
        self.assertNotIn('🏠', body)            # no emoji nav


class OverviewStubTest(DashboardShellTest):
    def test_overview_renders_sample(self):
        self.login_as(self.owner)
        r = self.client.get('/dashboard/overview/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('class="stat"', body)
        self.assertIn('Sample data', body)   # explicit sample marker


class OrdersStubTest(DashboardShellTest):
    def test_orders_renders_sample(self):
        self.login_as(self.owner)
        r = self.client.get('/dashboard/orders/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('class="tbl"', body)
        self.assertIn('Sample data', body)
