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


class BranchesScreenTest(DashboardShellTest):
    def setUp(self):
        super().setUp()
        from menu.models import Branch
        Branch.objects.create(company=self.company, name='Lake Center', slug='lake')

    def test_branches_lists_real(self):
        self.login_as(self.owner)
        r = self.client.get('/dashboard/branches/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Lake Center')
        self.assertContains(r, 'class="bcard"')


class QrSkinTest(DashboardShellTest):
    def setUp(self):
        super().setUp()
        from menu.models import Branch
        Branch.objects.create(company=self.company, name='Lake Center', slug='lake')

    def test_qr_card_grid(self):
        self.login_as(self.owner)
        r = self.client.get('/dashboard/qr/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'class="qgrid"')
        self.assertContains(r, 'Lake Center')


class SettingsSkinTest(DashboardShellTest):
    def test_settings_sections(self):
        self.login_as(self.owner)
        r = self.client.get('/dashboard/settings/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'class="set-grid"')
        self.assertContains(r, 'Guest menu theme')
        self.assertContains(r, 'data-theme-stub')   # picker marked non-functional
        self.assertContains(r, self.company.name)


class MenuBuilderTest(DashboardShellTest):
    def setUp(self):
        super().setUp()
        from menu.models import Category, MenuItem
        # Items are a flat company-level library; category placement is per-branch
        # (BranchItemPlacement), so the dashboard builder shows real categories as
        # structure and the item library as rows — no company-level item→category link.
        Category.objects.create(company=self.company, name='Juices', slug='juices',
                                display_order=1)
        MenuItem.objects.create(company=self.company, name='Sea-Buckthorn',
                                slug='sea-buckthorn', price=320)

    def test_builder_lists_items(self):
        self.login_as(self.owner)
        r = self.client.get('/dashboard/items/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Sea-Buckthorn')
        self.assertContains(r, 'Rs 320')
        # Two-pane builder markup: real category block + item-library rows + library pane
        self.assertContains(r, 'class="cat"')
        self.assertContains(r, 'class="row"')
        self.assertContains(r, 'Item library')


class ItemEditorTest(DashboardShellTest):
    def setUp(self):
        super().setUp()
        from menu.models import MenuItem
        # MenuItemForm has no category field; items are flat (placement is per-branch).
        self.item = MenuItem.objects.create(company=self.company, name='Sea-Buckthorn',
                                            slug='sea-buckthorn', price=320,
                                            focal_x=50, focal_y=50)

    def test_editor_renders_focal(self):
        # Focal picker (wireframe .editor/.focal slide-over) renders even with no image.
        self.login_as(self.owner)
        r = self.client.get(f'/dashboard/items/{self.item.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'class="focal"')
        self.assertContains(r, 'name="focal_x"')

    def test_editor_persists_focal(self):
        # Regression guard: the re-skin must keep focal_x/y persistence working.
        self.login_as(self.owner)
        r = self.client.post(f'/dashboard/items/{self.item.pk}/', {
            'name': 'Sea-Buckthorn', 'price': '320',
            'focal_x': '70', 'focal_y': '30',
        })
        self.assertIn(r.status_code, (302, 200))
        self.item.refresh_from_db()
        self.assertEqual((self.item.focal_x, self.item.focal_y), (70, 30))
