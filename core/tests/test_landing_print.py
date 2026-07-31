"""The redrawn Georgian block-print ornament (spec 2026-07-30).

The guards here exist because every one of them protects a failure that is
invisible in review: a mask only paints uncoloured shapes, a tile whose motifs
overflow its box shows a stitch every 120px, and a CSS rule in the wrong place
renders the dashboard's mobile shell wrong while every assertion still passes.
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from django.conf import settings
from django.test import SimpleTestCase

SVG_NS = '{http://www.w3.org/2000/svg}'
PRINT_DIR = Path(settings.BASE_DIR) / 'static' / 'images' / 'print'
STRIP = PRINT_DIR / 'border-strip.svg'
ROSETTE = PRINT_DIR / 'rosette.svg'

_NUMBER = re.compile(r'-?\d+(?:\.\d+)?')
_TRANSLATE = re.compile(r'translate\(\s*(-?[\d.]+)[ ,]+(-?[\d.]+)\s*\)')


def _local_x_extent(el):
    """(min x, max x) of a motif defined at the origin in <defs>.

    Path data in these files uses only absolute M/L/C commands, whose numbers
    are coordinate pairs, so every even-indexed number is an x. Task 1 asserts
    that restriction separately -- an arc command would break this parse.
    """
    if el.tag == f'{SVG_NS}circle':
        cx, r = float(el.get('cx', 0)), float(el.get('r', 0))
        return cx - r, cx + r
    nums = [float(n) for n in _NUMBER.findall(el.get('d', ''))]
    xs = nums[0::2]
    return min(xs), max(xs)


def _placed_x_extent(svg_path):
    """(min x, max x) actually painted, after every <use> is positioned."""
    root = ET.parse(svg_path).getroot()
    motifs = {}
    for parent in root.iter(f'{SVG_NS}defs'):
        for el in parent:
            motifs[el.get('id')] = _local_x_extent(el)
    lo, hi = [], []
    for use in root.iter(f'{SVG_NS}use'):
        ref = (use.get('href') or use.get(
            '{http://www.w3.org/1999/xlink}href', '')).lstrip('#')
        left, right = motifs[ref]
        transform = use.get('transform', '')
        dx, dy = _TRANSLATE.search(transform).groups()
        if 'scale(-1' in transform.replace(' ', ''):
            left, right = -right, -left
        lo.append(float(dx) + left)
        hi.append(float(dx) + right)
    return min(lo), max(hi)


class PrintAssetsTest(SimpleTestCase):
    def test_both_assets_exist(self):
        self.assertTrue(STRIP.exists(), f'missing {STRIP}')
        self.assertTrue(ROSETTE.exists(), f'missing {ROSETTE}')

    def test_assets_declare_a_viewbox_and_intrinsic_size(self):
        """A CSS mask image with no intrinsic size cannot be scaled predictably."""
        strip = ET.parse(STRIP).getroot()
        self.assertEqual(strip.get('viewBox'), '0 0 120 28')
        self.assertEqual((strip.get('width'), strip.get('height')), ('120', '28'))
        rosette = ET.parse(ROSETTE).getroot()
        self.assertEqual(rosette.get('viewBox'), '0 0 200 200')

    def test_no_asset_carries_a_colour_of_its_own(self):
        """A mask paints by alpha and the CSS supplies the colour. An
        uncoloured shape defaults to opaque black, which is what a mask wants;
        a baked-in fill would silently break the dark section's recolouring."""
        for path in (STRIP, ROSETTE):
            text = path.read_text()
            self.assertIsNone(re.search(r'\bfill=', text),
                              f'{path.name} carries a fill colour')
            self.assertIsNone(re.search(r'\bstroke=', text),
                              f'{path.name} carries a stroke — line work must '
                              f'be filled shapes, since stroke defaults to none')

    def test_the_strip_uses_only_pair_coordinate_commands(self):
        """Arc and relative commands would break both the seam check below and
        the assumption that every even-indexed number is an x."""
        for el in ET.parse(STRIP).getroot().iter():
            d = el.get('d')
            if d:
                self.assertIsNone(re.search(r'[AaHhVvSsQqTtcmlz]', d),
                                  f'unsupported path command in {d!r}')

    def test_no_motif_crosses_the_tile_edge(self):
        """A tile whose motifs overflow its box shows a visible stitch every
        120px across a full-width band. The tile is designed so the repeat
        rhythm comes from even spacing INSIDE the box, which makes seamlessness
        a checkable property rather than a judgement call."""
        low, high = _placed_x_extent(STRIP)
        self.assertGreaterEqual(low, 0, 'a motif overflows the left edge')
        self.assertLessEqual(high, 120, 'a motif overflows the right edge')

    def test_each_row_of_the_tile_closes_on_the_seam(self):
        """The edge check above is necessary but NOT sufficient: motifs can sit
        wholly inside the box and still break rhythm across a repeat. A row is
        seamless only when its motif count times its step equals the tile width,
        so the last motif of one tile is exactly one step from the first of the
        next.

        The original tile failed exactly this: 11 motifs at a 10-unit step
        spanned 110 of 120, putting a 20-unit gap and two adjacent diamonds at
        every seam. The edge check passed the whole time.
        """
        rows = {}
        for use in ET.parse(STRIP).getroot().iter(f'{SVG_NS}use'):
            ref = (use.get('href') or '').lstrip('#')
            dx, dy = _TRANSLATE.search(use.get('transform', '')).groups()
            rows.setdefault(float(dy), []).append((float(dx), ref))
        self.assertEqual(len(rows), 3, 'expected three stacked rows')
        for y, motifs in sorted(rows.items()):
            motifs.sort()
            xs = [x for x, _ in motifs]
            steps = {round(b - a, 6) for a, b in zip(xs, xs[1:])}
            self.assertEqual(len(steps), 1, f'row y={y} has an uneven step: {steps}')
            step = steps.pop()
            self.assertEqual(len(xs) * step, 120,
                             f'row y={y}: {len(xs)} motifs x {step} != 120 — the '
                             f'rhythm breaks at every tile seam')
            self.assertEqual(len(motifs) % 2, 0,
                             f'row y={y} has an odd motif count, so an '
                             f'alternating sequence cannot continue across tiles')

    def test_the_rosette_has_twelvefold_symmetry(self):
        """Twelve-fold is what makes the medallion read as a medallion rather
        than as a flower. Built by rotating one petal, so the count is the
        design, not decoration.

        Filtered to the petals: the bead ring is offset 15 degrees so its beads
        sit in the petals' gaps, and counting both together would assert
        twenty-four-fold symmetry that nothing in the design has.
        """
        angles = {}
        for use in ET.parse(ROSETTE).getroot().iter(f'{SVG_NS}use'):
            ref = (use.get('href') or '').lstrip('#')
            match = re.search(r'rotate\((\d+)', use.get('transform', ''))
            if match:
                angles.setdefault(ref, set()).add(int(match.group(1)))
        self.assertEqual(sorted(angles['petal']), list(range(0, 360, 30)))
        self.assertEqual(sorted(angles['bead']), list(range(15, 360, 30)))


class PrintCssTest(SimpleTestCase):
    def _css(self):
        path = Path(settings.BASE_DIR) / 'static' / 'css' / 'app.css'
        self.assertTrue(path.exists(), 'app.css not built — run bin/build-css.sh')
        return path.read_text()

    def test_the_print_classes_survive_tailwinds_tree_shaking(self):
        """Tailwind drops unused single-class @layer components rules. The
        anchor matters: a bare substring would also match inside a compound
        selector and pass while the rule itself is gone."""
        css = self._css()
        for cls in ('mk-print-rule', 'mk-print-dark', 'mk-print-rosette'):
            self.assertRegex(css, r'[}{]\.' + cls + r'\{',
                             f'.{cls} missing from the built CSS')

    def test_the_ink_tokens_are_defined(self):
        css = self._css()
        for token in ('--print-ink:#172d42', '--print-deep:#0f2030'):
            self.assertIn(token, css.replace(' ', ''), f'missing token {token}')

    def test_print_rules_precede_the_mobile_dashboard_overrides(self):
        """Source order decides the cascade between rules of equal specificity,
        and the <900px dashboard shell is documented as needing to stay last:
        its .side and .top rules share specificity with their bases above.
        Asserting presence alone would pass while the shell rendered wrong.

        Anchored on `.side{display:none}` rather than on the breakpoint:
        `899.98px` appears three times in this stylesheet, and two unrelated
        one-line overrides come earlier, so matching the breakpoint compares
        against the wrong block and can never fail.
        """
        css = self._css()
        anchor = '.side{display:none}'
        self.assertEqual(css.count(anchor), 1,
                         'the mobile-shell anchor is no longer unique — pick a '
                         'new one rather than matching the wrong block')
        last_print = max(m.start() for m in
                         re.finditer(r'[}{]\.mk-print-[a-z]+\{', css))
        self.assertLess(last_print, css.index(anchor),
                        'print CSS was appended after the mobile dashboard block')

    def test_the_mask_is_painted_by_currentcolor_not_a_baked_in_colour(self):
        """One asset, two colourways. If the rule painted a fixed colour, the
        dark section would need a second file kept in sync by hand."""
        css = self._css()
        rule = css[css.index('.mk-print-rule{'):]
        rule = rule[:rule.index('}') + 1]
        self.assertIn('currentColor', rule)
        self.assertIn('border-strip.svg', rule)

    def test_the_mask_carries_the_webkit_prefix(self):
        """Safari needs -webkit-mask; without it the element renders as a solid
        indigo bar across the page rather than as ornament."""
        css = self._css()
        rule = css[css.index('.mk-print-rule{'):]
        rule = rule[:rule.index('}') + 1]
        self.assertIn('-webkit-mask', rule)


@pytest.mark.django_db
def test_the_landing_carries_printed_dividers(client):
    """The dividers are the thread that ties the page together; an include
    dropped in a later edit would remove them silently."""
    body = client.get('/en/').content.decode()
    assert body.count('mk-print-rule') == 4          # 3 dividers + the footer band
    assert 'aria-hidden="true"' in body


@pytest.mark.django_db
def test_the_dividers_are_decorative_to_assistive_tech(client):
    """They carry no text and no meaning. An empty div in a landmark is exactly
    the thing a future refactor accidentally gives content to.

    The match count is asserted before the loop: this regex depends on the
    markup's attribute order, so a template reformat could otherwise leave it
    matching nothing and silently asserting nothing at all.
    """
    body = client.get('/en/').content.decode()
    fragments = re.findall(r'<div class="mk-print-rule"[^>]*>', body)
    assert len(fragments) == 4
    for fragment in fragments:
        assert 'aria-hidden="true"' in fragment


def _linear(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def contrast(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class PrintContrastTest(SimpleTestCase):
    """Recolouring a dark section is where an accent decision quietly becomes an
    accessibility defect. Same floors the guest themes are held to."""

    DEEP, PANEL, INK = '#0f2030', '#16304a', '#9db2c9'

    def test_body_text_on_the_indigo_ground_clears_aa(self):
        self.assertGreaterEqual(contrast(self.INK, self.DEEP), 4.5)

    def test_body_text_on_the_indigo_panels_clears_aa(self):
        self.assertGreaterEqual(contrast(self.INK, self.PANEL), 4.5)

    def test_white_headings_clear_aa_on_both_surfaces(self):
        self.assertGreaterEqual(contrast('#ffffff', self.DEEP), 4.5)
        self.assertGreaterEqual(contrast('#ffffff', self.PANEL), 4.5)


@pytest.mark.django_db
def test_the_multibranch_section_is_printed_indigo(client):
    body = client.get('/en/').content.decode()
    assert 'mk-print-dark' in body
    assert 'mk-print-rosette' in body


@pytest.mark.django_db
def test_the_stat_numbers_keep_the_saffron_gradient(client):
    """Deliberate (spec 6.2): warm on cool is the strongest pairing on the page,
    and it keeps the action colour present in the one fully-indigo section. A
    reviewer must not 'fix' this."""
    body = client.get('/en/').content.decode()
    section = body[body.index('mk-print-dark'):]
    section = section[:section.index('</section>')]
    assert section.count('mk-grad-text') == 3
