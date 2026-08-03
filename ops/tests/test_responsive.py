import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase


class OpsResponsiveCssTest(SimpleTestCase):
    """Built-CSS assertions for the ops mobile pass. app.css is MINIFIED —
    regexes use \\s* between tokens. Cascade guards follow the pattern from
    menu/tests/test_frontend.py::MobileShellCssTest: equal-specificity mobile
    overrides must FOLLOW their base rules in source order."""

    def _css(self):
        return (Path(settings.BASE_DIR) / 'static/css/app.css').read_text()

    def test_new_status_chip_classes_present(self):
        css = self._css()
        for sel in ['.ops-chip.follow_up', '.ops-chip.demo_scheduled']:
            self.assertIn(sel, css, f'missing chip style {sel}')

    def test_ops_card_classes_present(self):
        # Each class must open its OWN rule ([}{] anchor), not merely appear
        # inside another selector — .ops-card .actions .ops-status{…} contains
        # the substring '.ops-status{', which once masked the base rule being
        # tree-shaken as unused (safelist gap).
        css = self._css()
        for cls in ['ops-cards', 'ops-card', 'ops-status']:
            self.assertIsNotNone(
                re.search(r'[}{]\.' + cls + r'\{', css),
                f'missing standalone base rule for .{cls}')

    def test_ops_cards_show_override_after_hide_base(self):
        # Base hides the card list (desktop); the <900px override shows it.
        # Same specificity -> source order decides.
        css = self._css()
        base = re.search(r'\.ops-cards\s*\{\s*display:\s*none\s*\}', css)
        override = re.search(r'\.ops-cards\s*\{[^}]*display:\s*flex[^}]*\}', css)
        self.assertIsNotNone(base, 'base .ops-cards{display:none} missing')
        self.assertIsNotNone(override, 'mobile .ops-cards{display:flex} missing')
        self.assertGreater(override.start(), base.start(),
                           '.ops-cards show-override must come AFTER the hide base '
                           'rule or cards never appear under 900px')

    def test_ops_table_hidden_only_in_mobile_block(self):
        # .ops-table{display:none} must live in the trailing mobile block,
        # i.e. AFTER the base .table-scroll rule it effectively overrides.
        css = self._css()
        base = re.search(r'\.table-scroll\s*\{[^}]*overflow-x', css)
        override = re.search(r'\.ops-table\s*\{\s*display:\s*none\s*\}', css)
        self.assertIsNotNone(base, 'base .table-scroll rule missing')
        self.assertIsNotNone(override, 'mobile .ops-table{display:none} missing')
        self.assertGreater(override.start(), base.start(),
                           '.ops-table hide must come after the .table-scroll base rule')

    def test_ops_form_fullwidth_override_after_base(self):
        # Mobile drops the 560px fieldset cap. Base sets max-width:560px.
        css = self._css()
        base = re.search(r'\.ops-form\s+fieldset\s*\{[^}]*560px[^}]*\}', css)
        override = re.search(r'\.ops-form\s+fieldset\s*\{[^}]*max-width:\s*none[^}]*\}', css)
        self.assertIsNotNone(base, 'base .ops-form fieldset (560px) rule missing')
        self.assertIsNotNone(override, 'mobile .ops-form fieldset full-width missing')
        self.assertGreater(override.start(), base.start(),
                           'full-width override must come after the 560px base rule')


class WizardResponsiveCssTest(SimpleTestCase):
    """The menu-build wizard's own built-CSS guards (phase 4a).

    The `wz-` rules are single-class `@layer components` rules, which is the
    exact shape Tailwind tree-shakes when it cannot see the class in a
    template — and they carry <900px overrides at equal specificity, where
    source order is the only thing deciding the winner. Both traps have
    reached this project before, so they are pinned rather than trusted.
    """

    def _css(self):
        return (Path(settings.BASE_DIR) / 'static/css/app.css').read_text()

    def test_wizard_base_rules_survived_the_purge(self):
        # `[}{]` anchored so a match inside a compound selector (.wz-doc .btn)
        # cannot stand in for the base rule actually being present.
        css = self._css()
        for cls in ['wz-grid', 'wz-card', 'wz-pickgrid', 'wz-pick', 'wz-drop',
                    'wz-doc', 'wz-docs', 'wz-st', 'wz-bar', 'wz-note']:
            self.assertIsNotNone(
                re.search(r'[}{,]\.' + cls + r'[{,]', css),
                f'missing standalone base rule for .{cls}')

    def test_wizard_single_column_overrides_come_after_their_base(self):
        # Base lays the cards out in an auto-fill grid; <900px collapses both
        # grids to one column. Equal specificity -> whichever is later wins.
        css = self._css()
        for cls in ['wz-grid', 'wz-pickgrid']:
            base = re.search(r'[}{,]\.' + cls + r'\{[^}]*repeat\(auto-fill[^}]*\}', css)
            override = re.search(
                r'[}{,]\.' + cls + r'\{[^}]*grid-template-columns:\s*1fr[^}]*\}', css)
            self.assertIsNotNone(base, f'base .{cls} auto-fill rule missing')
            self.assertIsNotNone(override, f'mobile .{cls} single-column rule missing')
            self.assertGreater(
                override.start(), base.start(),
                f'.{cls} single-column override must come AFTER the auto-fill base '
                'rule or the wizard stays multi-column on a phone')

    def test_wizard_mobile_actions_are_thumb_sized(self):
        # Every wizard action is a real tap target under 900px. A control that
        # only appears on hover, or lands under 44px, is unusable on the phone
        # the staff member is actually holding at the venue.
        css = self._css()
        self.assertIsNotNone(
            re.search(r'\.wz-cta\s+\.btn[^{]*\{[^}]*min-height:\s*44px', css),
            'wizard mobile actions must carry a 44px min-height')


APEX = settings.BASE_DOMAIN


class OpsMobileShellTests(TestCase):
    def setUp(self):
        self.apex = {'HTTP_HOST': APEX}
        boss = User.objects.create_superuser('boss', 'b@x.io', 'pw')
        self.client.force_login(boss)

    def test_tabbar_present_with_three_links_and_signout(self):
        body = self.client.get('/platform/leads', **self.apex).content.decode()
        self.assertIn('class="tabbar"', body)
        tabbar = body.split('class="tabbar"', 1)[1]
        self.assertIn('/platform/leads', tabbar)
        self.assertIn('/platform/tenants', tabbar)
        self.assertIn('/platform/tenants/new', tabbar)
        self.assertIn('/platform/logout', tabbar)   # sign-out POST form in the bar

    def test_the_superseded_scan_path_is_not_offered_anywhere_in_the_shell(self):
        """Founder call 2026-08-01: the Gemini-backed Images/Scans path is
        superseded by the menu-build wizard and must not be reachable from the
        nav. The routes still resolve on purpose — phase 4 reuses the workbench
        and publish code — so only the offer is gone, and this pins it against a
        future session helpfully putting the links back."""
        body = self.client.get('/platform/leads', **self.apex).content.decode()
        self.assertNotIn('/platform/images', body)
        self.assertNotIn('/platform/scans', body)

    def test_tabbar_active_state_follows_page(self):
        body = self.client.get('/platform/tenants', **self.apex).content.decode()
        tabbar = body.split('class="tabbar"', 1)[1]
        self.assertIn('tb on', tabbar)

    def test_login_page_has_no_tabbar(self):
        self.client.logout()
        body = self.client.get('/platform/login', **self.apex).content.decode()
        self.assertNotIn('class="tabbar"', body)
