"""Registry tests for the 6 guest-menu theme palettes (pure Python, no DB)."""
import re

from django.test import SimpleTestCase

from menu.themes import (
    DEFAULT_THEME, GROUP_LABELS, THEME_CHOICES, THEMES, TOKEN_KEYS,
    get_theme, resolve_slug,
)

HEX_RE = re.compile(r'^#[0-9A-F]{6}$')
GRAD_RE = re.compile(r'^linear-gradient\(135deg,#[0-9A-F]{6},#[0-9A-F]{6}\)$')


def _linear(channel):
    c = channel / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def contrast(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class ThemeRegistryTest(SimpleTestCase):
    def test_six_themes_in_group_order(self):
        self.assertEqual(
            list(THEMES),
            ['fastfood', 'citrus', 'contrast', 'eco', 'cozy', 'herbal'])
        groups = [t.group for t in THEMES.values()]
        self.assertEqual(groups, sorted(groups), 'group 1 must precede group 2')

    def test_default_is_eco(self):
        self.assertEqual(DEFAULT_THEME, 'eco')
        self.assertIn(DEFAULT_THEME, THEMES)

    def test_choices_mirror_registry(self):
        self.assertEqual(
            THEME_CHOICES, [(slug, t.label) for slug, t in THEMES.items()])

    def test_group_labels(self):
        self.assertEqual(GROUP_LABELS[1], 'Appetite Stimulators')
        self.assertEqual(GROUP_LABELS[2], 'Trust & Comfort')

    def test_every_theme_defines_full_token_vocabulary(self):
        self.assertEqual(len(TOKEN_KEYS), 14)
        for slug, theme in THEMES.items():
            self.assertEqual(tuple(theme.tokens), TOKEN_KEYS,
                             f'{slug} token keys/order mismatch')

    def test_token_values_are_hex_or_gradient(self):
        for slug, theme in THEMES.items():
            for key, value in theme.tokens.items():
                pattern = GRAD_RE if key == '--grad' else HEX_RE
                self.assertRegex(value, pattern, f'{slug} {key} = {value!r}')

    def test_swatches_are_three_hexes(self):
        for slug, theme in THEMES.items():
            self.assertEqual(len(theme.swatch), 3, slug)
            for c in theme.swatch:
                self.assertRegex(c, HEX_RE, f'{slug} swatch {c!r}')

    def test_taglines_present(self):
        for slug, theme in THEMES.items():
            self.assertTrue(theme.tagline, f'{slug} needs a tagline')

    def test_get_theme_fallback_never_raises(self):
        eco = THEMES['eco']
        self.assertIs(get_theme('cozy'), THEMES['cozy'])
        for bad in ('', 'saffron', 'berry', 'juice', 'neon', None):
            self.assertIs(get_theme(bad), eco)

    def test_resolve_slug(self):
        self.assertEqual(resolve_slug('herbal'), 'herbal')
        for bad in ('', 'saffron', 'nope', None):
            self.assertEqual(resolve_slug(bad), 'eco')


class ThemeContrastFloorsTest(SimpleTestCase):
    """WCAG floors from the spec: body ink on every surface >= 4.5 (AA normal),
    CTA text (--brand-ink) on --brand >= 3.0 (AA large/bold)."""

    def test_ink_on_surfaces_aa(self):
        for slug, t in THEMES.items():
            for surface in ('--paper', '--cream', '--card'):
                ratio = contrast(t.tokens['--ink'], t.tokens[surface])
                self.assertGreaterEqual(
                    ratio, 4.5, f'{slug}: --ink on {surface} = {ratio:.2f}')

    def test_brand_ink_on_brand_aa_large(self):
        for slug, t in THEMES.items():
            ratio = contrast(t.tokens['--brand-ink'], t.tokens['--brand'])
            self.assertGreaterEqual(
                ratio, 3.0, f'{slug}: --brand-ink on --brand = {ratio:.2f}')

    def test_price_readable_on_paper(self):
        for slug, t in THEMES.items():
            ratio = contrast(t.tokens['--price'], t.tokens['--paper'])
            self.assertGreaterEqual(
                ratio, 3.0, f'{slug}: --price on --paper = {ratio:.2f}')
