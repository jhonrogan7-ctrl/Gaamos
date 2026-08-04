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
        # `wz-drop` and `wz-docs` are deliberately absent: the build now starts
        # from a spreadsheet, so the multi-file drop zone and the document list
        # they styled are gone from the markup and Tailwind is right to purge
        # them. Pinning a class no template uses would only ever fail.
        # `wz-tile` replaces them — it is the generating screen's row card, and
        # it is a single-class @layer rule, which is exactly what gets purged.
        for cls in ['wz-grid', 'wz-card', 'wz-pickgrid', 'wz-pick', 'wz-tile',
                    'wz-tilegrid', 'wz-doc', 'wz-st', 'wz-bar', 'wz-note']:
            self.assertIsNotNone(
                re.search(r'[}{,]\.' + cls + r'[{,]', css),
                f'missing standalone base rule for .{cls}')

    def test_the_tile_grid_does_not_reuse_the_card_grid_class(self):
        """`.wz-grid` lays out build cards at minmax(290px) on the list, review
        and published screens. The generating screen's picture tiles are much
        smaller, and when they were written as a second `.wz-grid` rule they won
        by source order and silently halved the card width on all three.
        """
        css = self._css()

        self.assertIsNone(
            re.search(r'[}{,]\.wz-grid\{[^}]*minmax\(148px', css),
            'the tile sizing is back on .wz-grid — it will shrink the build '
            'cards on the list, review and published screens')
        self.assertIsNotNone(
            re.search(r'[}{,]\.wz-tilegrid\{[^}]*minmax\(148px', css),
            'the tile grid lost its own sizing')
        self.assertIsNotNone(
            re.search(r'[}{,]\.wz-grid\{[^}]*minmax\(290px', css),
            'the build-card grid lost its own sizing')

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

    def test_gate1_split_collapses_after_its_desktop_base(self):
        # Gate 1 is ONE layout at both sizes: the photo-beside-rows split
        # collapses to a stack under 900px. Same specificity, so if the
        # override ever sorts before the base the phone gets a 340px photo
        # pane beside the rows at 360px wide -- unusable, and invisible to
        # every assertion that only checks the rule exists.
        css = self._css()
        base = re.search(r'[}{,]\.wz-split\{[^}]*grid-template-columns:\s*minmax[^}]*\}', css)
        override = re.search(
            r'[}{,]\.wz-split\{[^}]*grid-template-columns:\s*1fr[^}]*\}', css)
        self.assertIsNotNone(base, 'desktop .wz-split two-column base missing')
        self.assertIsNotNone(override, 'mobile .wz-split stack override missing')
        self.assertGreater(override.start(), base.start(),
                           '.wz-split stack override must come AFTER the two-column base')

    def test_gate1_row_actions_are_not_hover_only(self):
        # The founder rule this screen is most likely to lose: the wireframe
        # reveals edit/delete on hover, and hover does not exist on touch. The
        # price and the ... sheet are always-visible controls with real tap
        # targets, so neither may be gated behind :hover.
        css = self._css()
        for cls in ['wz-row-pr', 'wz-row-more']:
            rule = re.search(r'[}{,]\.' + cls + r'\{[^}]*\}', css)
            self.assertIsNotNone(rule, f'.{cls} base rule missing')
            self.assertIn('min-height:44px', rule.group(0).replace(' ', ''),
                          f'.{cls} must be a real tap target')
        self.assertIsNone(
            re.search(r'\.wz-row[a-z-]*:hover\{[^}]*(display|visibility|opacity)', css),
            'no wizard row control may be revealed by hover -- touch has none')

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


class OpsShellRunsItsJavascriptTest(TestCase):
    """A page that USES Alpine must LOAD Alpine.

    This is the gap that shipped the phase-4a wizard with every interactive
    control dead: `ops/base.html` loaded HTMX but not Alpine, so `x-data`,
    `x-show` and `@click` were inert -- and because the built CSS carries
    `[x-cloak]{display:none !important}`, every `x-cloak` element was hidden
    PERMANENTLY rather than merely un-animated.

    Nothing caught it. The test client renders templates without executing
    them, and curl fetches the same markup: an element that never un-hides
    still *appears* in the HTML, so every presence assertion passed. The only
    honest check at this layer is that the runtime is on the page at all.
    """

    def setUp(self):
        self.apex = {'HTTP_HOST': APEX}
        self.client.force_login(User.objects.create_superuser('boss', 'b@x.io', 'pw'))

    def _pages(self):
        from menu.models import Branch, Company, MenuBuild, MenuBuildSection
        company = Company.objects.create(name='Kailash Parbat', slug='kailash')
        Branch.all_objects.create(company=company, name='Lakeside', slug='lakeside')
        build = MenuBuild.objects.create(company=company, status='gate1')
        MenuBuildSection.objects.create(build=build, name='JUICE')
        return ['/platform/builds/', '/platform/builds/new/',
                f'/platform/builds/{build.pk}/gate1/',
                f'/platform/builds/{build.pk}/review/']

    def test_every_ops_page_using_alpine_also_loads_it(self):
        for url in self._pages():
            html = self.client.get(url, **self.apex).content.decode()
            if 'x-data' in html:
                self.assertIn(
                    'alpine', html.lower(),
                    f'{url} uses Alpine directives but never loads Alpine -- '
                    'every x-show/@click on it is dead and every x-cloak '
                    'element is hidden for good')

    def test_the_ops_shell_serves_alpine_locally(self):
        # From `static/vendor/`, like `templates/base.html` -- not a CDN. The
        # platform screens are staff tools that must work on a venue's wifi.
        html = self.client.get('/platform/builds/new/', **self.apex).content.decode()
        self.assertIn('vendor/alpine.min.js', html)
