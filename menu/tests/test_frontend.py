from pathlib import Path
from django.conf import settings
from django.test import SimpleTestCase, override_settings
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
        body = r.content.decode()
        self.assertNotIn('data-theme-stub', body)             # picker is live now
        self.assertIn('/dashboard/settings/theme/', body)     # posts the default theme
        self.assertIn('Default guest menu theme', body)
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
                    '.k-qty', '.k-pill', '.g-mono', '.vb-tab', '.vc-ti']:
            self.assertIn(sel, css, f'missing guest kit class {sel}')

    def test_theme_colors_no_longer_live_in_css(self):
        # Themes are data-driven: tokens are emitted inline on the guest <html>
        # from menu/themes.py; built CSS must carry no per-theme color blocks.
        src = (Path(settings.BASE_DIR) / 'static/css/input.css').read_text()
        self.assertNotIn('[data-theme="berry"]', src)
        self.assertNotIn('[data-theme="juice"]', src)
        self.assertNotIn('--price:', src)
        self.assertNotIn('--brand: var(--accent)', src)

    def test_guest_gradient_uses_grad_token(self):
        # Guest kit must key off --grad (inline token), never the dashboard's
        # :root --accent-grad; marketing/.mk-* keeps --accent-grad untouched.
        src = (Path(settings.BASE_DIR) / 'static/css/input.css').read_text()
        guest = src[src.index('GUEST MENU (ported from donor menu.css'):]
        self.assertNotIn('var(--accent-grad', guest)
        self.assertIn('var(--grad, var(--brand))', guest)

    def test_marketing_base_has_no_phantom_company_theme(self):
        html = (Path(settings.BASE_DIR) / 'templates/base.html').read_text()
        self.assertNotIn('company.theme', html)
        self.assertIn('theme_style', html)

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
        self.assertIn("app.js' %}?v=16", html.replace('"', "'"))


class GuestSharedScreensTest(TenantTestCase):
    def _html(self):
        return self.client.get('/').content.decode()

    def test_no_hardcoded_juicery_logo(self):
        # F2: brand comes from the tenant; no donor logo anywhere.
        self.assertNotIn('juicery_logo', self._html())

    def test_no_agency_or_donor_footer(self):
        # F13
        html = self._html()
        self.assertNotIn('Twenty Two Tech', html)
        self.assertNotIn('The Juicery Cafe.', html)

    def test_no_dead_promo_or_sort_controls(self):
        # F7
        html = self._html()
        self.assertNotIn('Promo code', html)
        self.assertNotIn('Sort by', html)

    def test_placed_screen_present(self):
        # F11: persistent confirmation screen exists in the SPA template.
        html = self._html()
        self.assertIn("screen === 'placed'", html)
        self.assertIn('Order placed', html)


class MenuLayoutPartialsTest(TenantTestCase):
    def test_baseline_partial_served_by_default(self):
        html = self.client.get('/').content.decode()
        self.assertIn('data-layout="baseline"', html)

    def test_tabs_partial_served_on_preview(self):
        html = self.client.get('/?layout=tabs').content.decode()
        self.assertIn('data-layout="tabs"', html)
        self.assertNotIn('data-layout="baseline"', html)

    def test_iconrail_partial_served_on_preview(self):
        html = self.client.get('/?layout=iconrail').content.decode()
        self.assertIn('data-layout="iconrail"', html)


@override_settings(BASE_DOMAIN='zxyn.online', ALLOWED_HOSTS=['.zxyn.online', 'testserver'])
class DashboardCsrfHelperTest(TenantTestCase):
    """The dashboard's fetch() POSTs (branch builder delete/add, categories
    add/remove) send `X-CSRFToken: getCookie('csrftoken')`. The guest `app.js`
    that defines getCookie is NOT loaded on dashboard pages, so getCookie must be
    defined there or every POST throws ReferenceError and silently no-ops."""

    HOST = 'testco.zxyn.online'  # resolves to the TenantTestCase company (slug=testco)

    def setUp(self):
        super().setUp()
        from menu.models import Branch
        User = get_user_model()
        u = User.objects.create_user('mgr', password='pass', is_staff=True)
        self.make_owner(u)
        self.client.login(username='mgr', password='pass')
        Branch.objects.create(company=self.company, name='Main', slug='main', address='X')

    def test_branch_builder_page_defines_getcookie(self):
        body = self.client.get('/dashboard/branch/main/', HTTP_HOST=self.HOST).content.decode()
        self.assertIn('getCookie(', body, 'branch builder should reference getCookie')
        self.assertIn('function getCookie', body,
                      'branch builder calls getCookie but never defines it — POSTs no-op')

    def test_categories_page_defines_getcookie(self):
        body = self.client.get('/dashboard/categories/', HTTP_HOST=self.HOST).content.decode()
        if 'getCookie(' in body:
            self.assertIn('function getCookie', body,
                          'categories page calls getCookie but never defines it')


class MobileShellCssTest(SimpleTestCase):
    """CSS for the <900px dashboard shell: bottom tab bar + More sheet.
    Desktop (>=900px) keeps the sidebar; exactly one nav is visible at any width."""

    def _css(self):
        return (Path(settings.BASE_DIR) / 'static/css/app.css').read_text()

    def test_mobile_shell_classes_present(self):
        css = self._css()
        for sel in ['.tabbar', '.more-sheet', '.ms-panel', '.ms-backdrop']:
            self.assertIn(sel, css, f'missing mobile shell class {sel}')

    def test_shell_breakpoint_and_safe_area(self):
        css = self._css()
        self.assertIn('899.98px', css, 'missing <900px shell breakpoint')
        self.assertIn('env(safe-area-inset-bottom', css, 'missing iOS safe-area padding')

    def test_sidebar_hide_override_after_base_rule(self):
        # Cascade guard: the <900px .side{display:none} must appear AFTER the base
        # .side rule (which sets display:flex) in the built CSS — same specificity
        # means source order decides, and media-query nesting does not change
        # cascade order. If the override drifts back above the base rule, the
        # sidebar renders above the content on every mobile screen.
        import re
        css = self._css()
        base = re.search(r'\.side\s*\{[^}]*flex', css)
        override = re.search(r'\.side\s*\{\s*display:\s*none\s*\}', css)
        self.assertIsNotNone(base, 'base .side (flex) rule missing from app.css')
        self.assertIsNotNone(override, 'mobile .side{display:none} missing from app.css')
        self.assertGreater(override.start(), base.start(),
                           '.side{display:none} must come after the base .side rule '
                           'or the sidebar never hides under 900px')

    def test_top_compact_override_after_base_rule(self):
        # Same cascade guard for the top bar: the <900px compaction
        # (.top{gap:10px;padding:0 14px}) must follow the base .top rule
        # (min-height:62px; padding:0 24px) or the top bar never compacts.
        import re
        css = self._css()
        base = re.search(r'\.top\s*\{[^}]*62px', css)
        override = re.search(r'\.top\s*\{[^}]*gap:\s*10px[^}]*\}', css)
        self.assertIsNotNone(base, 'base .top (62px) rule missing from app.css')
        self.assertIsNotNone(override, 'mobile .top compaction rule missing from app.css')
        self.assertGreater(override.start(), base.start(),
                           'mobile .top override must come after the base rule '
                           'or the top bar never compacts under 900px')


class SheetDesktopDialogTest(SimpleTestCase):
    """The .sheet editor is a bottom sheet on mobile but must render as a
    centred dialog >=900px — bottom-anchored on a large monitor it reads as
    fallen off the bottom edge of the screen (settings 'Add branch' bug)."""

    def _css(self):
        return (Path(settings.BASE_DIR) / 'static/css/app.css').read_text()

    def test_desktop_backdrop_centers_after_mobile_base(self):
        # Cascade guard: same specificity, so the >=900px centring override
        # must appear AFTER the base flex-end (bottom sheet) rule.
        import re
        css = self._css()
        base = re.search(r'[}{]\.sheet-backdrop\{[^}]*flex-end', css)
        override = re.search(r'[}{]\.sheet-backdrop\{[^}]*align-items:center', css)
        self.assertIsNotNone(base, 'base .sheet-backdrop (flex-end) rule missing')
        self.assertIsNotNone(override, 'desktop .sheet-backdrop centring rule missing')
        self.assertGreater(override.start(), base.start(),
                           'desktop centring must come after the mobile base rule '
                           'or sheets stay bottom-anchored on desktop')

    def test_desktop_sheet_fully_rounded_after_mobile_base(self):
        import re
        css = self._css()
        base = re.search(r'[}{]\.sheet\{[^}]*border-radius:18px 18px 0 0', css)
        override = re.search(r'[}{]\.sheet\{[^}]*border-radius:18px[;}]', css)
        self.assertIsNotNone(base, 'base .sheet (top-rounded) rule missing')
        self.assertIsNotNone(override, 'desktop .sheet full-radius rule missing')
        self.assertGreater(override.start(), base.start(),
                           'desktop .sheet override must follow the mobile base rule')

    def test_desktop_hides_grab_handle(self):
        import re
        css = self._css()
        self.assertIsNotNone(
            re.search(r'[}{]\.sheet-handle\{display:none\}', css),
            'grab handle must be hidden on the desktop dialog')


class MobileShellTest(TenantTestCase):
    """Bottom tab bar + More sheet markup in the dashboard base template.
    Rendered at every width (CSS hides it >=900px), driven by active_tab."""

    def setUp(self):
        super().setUp()
        U = get_user_model()
        self.owner = U.objects.create_user('boss', password='pass')
        self.make_owner(self.owner)
        self.login_as(self.owner)

    def test_tabbar_present_with_four_tabs_and_more(self):
        body = self.client.get('/dashboard/overview/').content.decode()
        self.assertIn('class="tabbar"', body)
        for href in ['/dashboard/overview/', '/dashboard/orders/',
                     '/dashboard/branches/', '/dashboard/items/']:
            self.assertIn(href, body)
        self.assertIn('more-sheet', body)
        # More sheet contents: the three secondary links + sign out
        self.assertIn('/dashboard/categories/', body)
        self.assertIn('/dashboard/qr/', body)
        self.assertIn('/dashboard/settings/', body)

    def test_active_states(self):
        # Items screen -> Items tab on, More off
        body = self.client.get('/dashboard/items/').content.decode()
        self.assertRegex(body, r'class="tb on"[^>]*>\s*<svg[^>]*>.*?</svg>\s*<span>Items</span>')
        # Categories screen -> More button on (categories|qr|settings roll up to More)
        body = self.client.get('/dashboard/categories/').content.decode()
        self.assertRegex(body, r'<button[^>]*class="tb on"')

    def test_desktop_signout_tagged_for_hiding(self):
        # The top-bar sign-out form carries top-signout so CSS can hide it <900px
        # (the More sheet holds the mobile sign out).
        import re
        body = self.client.get('/dashboard/overview/').content.decode()
        self.assertIn('top-signout', body)
        # No inline style= on that form tag: an inline display would outrank
        # the stylesheet's display:none and keep the button visible <900px.
        m = re.search(r'<form[^>]*class="top-signout"[^>]*>', body)
        self.assertIsNotNone(m, 'top-signout form tag not found')
        self.assertNotIn('style=', m.group(0),
                         'inline style outranks .top .top-signout{display:none}')
        # And the built CSS actually hides it (allow minified output).
        css = (Path(settings.BASE_DIR) / 'static/css/app.css').read_text()
        self.assertRegex(css, r'\.top .top-signout\s*\{\s*display:\s*none',
                         'app.css must hide .top-signout under 900px')


class TableScrollTest(TenantTestCase):
    """Wide data tables scroll horizontally inside .table-scroll under 900px
    instead of stretching the page (no card-ification in this slice)."""

    def setUp(self):
        super().setUp()
        U = get_user_model()
        self.owner = U.objects.create_user('boss', password='pass')
        self.make_owner(self.owner)
        self.login_as(self.owner)

    def test_css_table_scroll_present(self):
        css = (Path(settings.BASE_DIR) / 'static/css/app.css').read_text()
        self.assertIn('.table-scroll', css)

    def test_set_grid_mobile_override_after_base_rule(self):
        # Cascade guard: the <900px .set-grid collapse must appear AFTER the base
        # 200px 1fr rule in the built CSS — same specificity means source order
        # decides, and media-query nesting does not change cascade order. If the
        # override drifts back above the base rule it silently never applies.
        import re
        css = (Path(settings.BASE_DIR) / 'static/css/app.css').read_text()
        base = re.search(r'\.set-grid\s*\{[^}]*200px 1fr', css)
        override = re.search(r'\.set-grid\s*\{\s*grid-template-columns:\s*1fr\s*\}', css)
        self.assertIsNotNone(base, 'base .set-grid (200px 1fr) rule missing from app.css')
        self.assertIsNotNone(override, 'mobile .set-grid { 1fr } override missing from app.css')
        self.assertGreater(override.start(), base.start(),
                           '.set-grid mobile override must come after the base rule '
                           'or the settings grid never collapses under 900px')

    def test_orders_queue_table_wrapped(self):
        body = self.client.get('/dashboard/orders/').content.decode()
        self.assertIn('table-scroll', body)

    def test_branch_tables_list_wrapped(self):
        # Deviation from brief: menu.models has no Restaurant model, and Branch
        # has no restaurant FK (see menu/tests/test_tables.py for the real
        # constructor shape). The branch-QR URL is namespaced 'branch/<slug>/qr/'
        # (menu/dashboard/urls.py), not 'branches/<slug>/qr/'.
        from menu.models import Branch, Table
        branch = Branch.objects.create(company=self.company, name='Main', slug='main')
        Table.objects.create(branch=branch, label='Patio 1')
        r = self.client.get(f'/dashboard/branch/{branch.slug}/qr/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('table-scroll', r.content.decode())


class BuilderSheetStackingTest(TenantTestCase):
    """The mobile bottom tab bar (z-index 40) must never cover the builder's
    library sheet or its Add-selected button. Regression: after the tab bar
    shipped, .lib-pane (z 30) rendered underneath it, hiding the button on
    phones/PWA. Assert real z values from the built CSS, not string presence."""

    def _z(self, css, selector_re):
        import re
        m = re.search(selector_re, css)
        self.assertIsNotNone(m, f'no z-index found for {selector_re}')
        return int(m.group(1))

    def test_lib_sheet_stacks_above_tabbar(self):
        css = (Path(settings.BASE_DIR) / 'static/css/app.css').read_text()
        z_tabbar = self._z(css, r'\.tabbar\{[^}]*z-index:(\d+)')
        z_libpane = self._z(css, r'\.lib-pane\{[^}]*z-index:(\d+)')
        z_backdrop = self._z(css, r'\.sheet-backdrop\.add-backdrop\{[^}]*z-index:(\d+)')
        self.assertGreater(z_backdrop, z_tabbar,
                           'add-item backdrop must dim/cover the tab bar')
        self.assertGreater(z_libpane, z_backdrop,
                           'library sheet must paint above its backdrop')

    def test_builder_page_has_no_inline_zindex_overrides(self):
        # Inline z-index styles beat every stylesheet rule and reintroduced the
        # tab-bar overlap; keep stacking in the CSS scale only.
        from menu.models import Branch
        U = get_user_model()
        owner = U.objects.create_user('boss', password='pass')
        self.make_owner(owner)
        self.login_as(owner)
        branch = Branch.objects.create(company=self.company, name='Main', slug='main')
        body = self.client.get(f'/dashboard/branch/{branch.slug}/').content.decode()
        self.assertNotIn('style="z-index:25;"', body)
        self.assertNotIn('style="z-index:40;"', body)


class BuilderAddSelectedGuardTest(TenantTestCase):
    """Second-add regression: after a successful add cleared addTarget, the
    always-visible desktop library still let items be ticked and showed an
    'Add N selected' button that was silently disabled. Pin the two JS guards."""

    def _builder_body(self):
        from menu.models import Branch
        U = get_user_model()
        owner = U.objects.create_user('boss', password='pass')
        self.make_owner(owner)
        self.login_as(owner)
        branch = Branch.objects.create(company=self.company, name='Main', slug='main')
        return self.client.get(f'/dashboard/branch/{branch.slug}/').content.decode()

    def test_toggle_select_requires_add_target(self):
        body = self._builder_body()
        self.assertIn('if (!this.addTarget) return;', body)

    def test_successful_add_keeps_target_on_desktop(self):
        body = self._builder_body()
        # success path clears selection and only closes the sheet on mobile
        self.assertIn("window.matchMedia('(min-width: 900px)')", body)
        self.assertNotIn('if (res.ok) { this.closeAdd(); await this.refresh(); }', body)


class MemberSheetCssTest(SimpleTestCase):
    def test_access_ui_classes_survive_build(self):
        import re
        css = (Path(settings.BASE_DIR) / 'static/css/app.css').read_text()
        for cls in ('acc-radio', 'fld-checks'):
            self.assertIsNotNone(
                re.search(r'[}{]\.' + cls + r'[ .{]', css),
                f'.{cls} missing from built app.css (purged or not built)')
