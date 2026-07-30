"""The redrawn Georgian block-print ornament (spec 2026-07-30).

The guards here exist because every one of them protects a failure that is
invisible in review: a mask only paints uncoloured shapes, a tile whose motifs
overflow its box shows a stitch every 120px, and a CSS rule in the wrong place
renders the dashboard's mobile shell wrong while every assertion still passes.
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

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
