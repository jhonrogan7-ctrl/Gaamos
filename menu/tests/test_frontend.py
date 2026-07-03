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

    def test_dashboard_shell_layout_present(self):
        # The .app grid places the sidebar in a fixed left column with main on the
        # right; without it the shell collapses (sidebar stacks above the content).
        css = self._css()
        self.assertIn('232px 1fr', css, 'missing .app sidebar/main grid layout')

    def test_overview_analytics_styles_present(self):
        # Overview's KPI grid, analytics grid, bar chart, top list and live feed
        # all need their component styles or the screen renders unstyled.
        css = self._css()
        for needle in ['1fr 340px', '.bars', '.toprow', '.feed']:
            self.assertIn(needle, css, f'missing overview style {needle}')

    def test_orders_section_styles_present(self):
        # The Orders queue header (section title + filter chip row) and the
        # order-number cells need their component styles.
        css = self._css()
        for needle in ['.sec-h', '.filters{', '.ono']:
            self.assertIn(needle, css, f'missing orders style {needle}')


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
    def test_orders_renders_live_queue(self):
        # Spec 3: global Orders renders the real live-queue table (empty here).
        self.login_as(self.owner)
        r = self.client.get('/dashboard/orders/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('class="tbl"', body)
        self.assertIn('Live order queue', body)


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


class GuestThemeTest(TenantTestCase):
    def test_guest_menu_uses_theme_and_app_css(self):
        # Guest menu must adopt the themed design system (data-theme + app.css),
        # dropping the old green menu.css.
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('data-theme', body)
        self.assertIn('css/app.css', body)
        self.assertNotIn('css/menu.css', body)
        self.assertNotIn('cdn.tailwindcss.com', body)


class GuestFlowTest(TenantTestCase):
    """The guest SPA ships the full flow (menu -> detail -> cart -> order placed
    -> venue), themed in T11. This guards that every flow screen renders and that
    order submission targets the real place_order endpoint."""

    def test_all_flow_screens_render_themed(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        # data-theme drives the palette on the whole flow
        self.assertIn('data-theme=', body)
        # Each flow screen's markup is present
        self.assertIn('Add to Order', body)      # item detail CTA
        self.assertIn('My Order', body)          # cart screen
        self.assertIn('Place Order', body)       # cart CTA
        self.assertIn('Order placed', body)      # confirmation / order modal
        self.assertIn('Our locations', body)     # venue / contact sheet
        # Themed flow components (ported into app.css) are used, not old greens
        self.assertIn('detail-img', body)
        self.assertIn('sticky-cta', body)

    def test_order_submission_targets_place_order_endpoint(self):
        from django.urls import reverse
        self.assertEqual(reverse('place_order'), '/api/order/')


class LoginSkinTest(TenantTestCase):
    def test_login_uses_app_css_and_gaamos_brand(self):
        r = self.client.get('/dashboard/login/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('css/app.css', body)
        self.assertNotIn('css/dashboard.css', body)
        self.assertNotIn('QR Manu', body)
        self.assertIn('Gaamos', body)


class AssetCacheBustTest(TenantTestCase):
    def test_app_css_links_are_cache_busted(self):
        # app.css keeps the same URL across rebuilds (no manifest hashing), so the
        # link must carry a content-version query or stale caches render unstyled.
        import re
        for path in ('/', '/dashboard/login/'):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertRegex(r.content.decode(), r'css/app\.css\?v=\w+', path)


class HomeSkinTest(DashboardShellTest):
    def test_home_uses_card_components(self):
        from menu.models import Branch
        Branch.objects.create(company=self.company, name='Main', slug='main')
        self.login_as(self.owner)
        r = self.client.get('/dashboard/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('class="cards"', body)      # gridded
        self.assertIn('bcard', body)              # themed card component
        self.assertNotIn('branch-card', body)     # old unstyled markup gone
        self.assertNotIn('🏪', body)              # no emoji


class GuestKitCssTest(SimpleTestCase):
    def _css(self):
        return (Path(settings.BASE_DIR) / 'static/css/app.css').read_text()

    def test_kit_classes_present(self):
        css = self._css()
        for sel in ['.k-card', '.k-monogram', '.k-price', '.k-tag', '.k-btn',
                    '.k-qty', '.k-pill', '.g-mono']:
            self.assertIn(sel, css, f'missing guest kit class {sel}')

    def test_price_token_defined_per_theme(self):
        src = (Path(settings.BASE_DIR) / 'static/css/input.css').read_text()
        self.assertEqual(src.count('--price:'), 3, 'expect one --price per theme')

    def test_sticky_cta_layered_above_detail(self):
        # F3: the detail CTA must carry an explicit stacking context.
        css = self._css()
        self.assertIn('.sticky-cta', css)
        src = (Path(settings.BASE_DIR) / 'static/css/input.css').read_text()
        self.assertRegex(src, r'\.sticky-cta\s*\{[^}]*z-index')


class GuestAppJsTest(SimpleTestCase):
    def _js(self):
        return (Path(settings.BASE_DIR) / 'static/js/app.js').read_text()

    def test_no_hardcoded_brunch_default(self):
        self.assertNotIn("'brunch'", self._js(),
                         'F1: default category must come from the payload')

    def test_others_group_rendered(self):
        self.assertIn("'Others'", self._js(),
                      'F14: un-subcategorised dishes must render in an Others group')

    def test_monogram_helper_and_layout_state(self):
        js = self._js()
        self.assertIn('monogram()', js)
        self.assertIn('layout:', js)

    def test_base_template_busts_js_cache(self):
        html = (Path(settings.BASE_DIR) / 'templates/menu/_base.html').read_text()
        self.assertIn("app.js' %}?v=14", html.replace('"', "'"))
