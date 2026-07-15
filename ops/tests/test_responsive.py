import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


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
