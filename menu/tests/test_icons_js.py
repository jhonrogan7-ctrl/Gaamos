"""The five icons a Nepali menu needs and the donor set never had.

Momo and thali are the sections a guest scans for first in this market; without
them Mo:Mo, Nepali Thali, Khaja Set and Paneer all render the same generic
plate.
"""
import re

from menu.tests.icons_js import ICONS_JS, defined_icon_keys

NEW = ['momo', 'thali', 'cereal', 'paneer', 'potato']


def test_the_new_category_icons_are_defined():
    keys = defined_icon_keys()
    assert set(NEW) <= keys


def test_the_new_icons_are_inline_svg_in_the_shared_style():
    """currentColor is what makes an icon inherit the venue's theme; a hardcoded
    colour would survive review by eye and then be wrong in the dark theme."""
    text = ICONS_JS.read_text()
    for key in NEW:
        body = re.search(rf"^\s{{2}}{key}:\s*'(.*?)',$", text, re.M).group(1)
        assert body.startswith('<svg ') and body.endswith('</svg>')
        assert 'viewBox="0 0 24 24"' in body
        assert 'stroke="currentColor"' in body
        assert '#' not in body, f'{key} hardcodes a colour'


def test_the_dashboard_picker_offers_them():
    """An owner must be able to CHOOSE the new icons, not only receive them
    from the pipeline."""
    from menu.dashboard.views import CATEGORY_ICON_CHOICES

    assert set(NEW) <= set(CATEGORY_ICON_CHOICES)


def test_every_picker_choice_has_an_svg():
    """The picker list and the SVG map are two separate lists that must agree.
    A choice with no SVG renders as its own literal key in the picker."""
    from menu.dashboard.views import CATEGORY_ICON_CHOICES, SUB_ICON_CHOICES

    assert set(CATEGORY_ICON_CHOICES) | set(SUB_ICON_CHOICES) <= defined_icon_keys()
