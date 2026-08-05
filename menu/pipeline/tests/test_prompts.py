"""Prompt composition, lifted out of the markdown parser.

The golden test is the point of this module's existence: these strings drew 557
photographs a guest orders from, and the refactor that let the wizard compose a
prompt without a sheet must not have changed a single character of them.
"""
import json
from collections import Counter
from pathlib import Path

import pytest
from django.conf import settings

from menu.pipeline import prompts

GOLDEN = json.loads(
    (Path(settings.BASE_DIR) / 'menu' / 'tests' / 'fixtures' / 'prompt_golden.json').read_text())

VENUES = {'tranquility-inn', 'chillzone', 'kailash-parbat', 'pokhara-metro-eco'}


def test_the_golden_fixture_covers_the_real_corpus():
    """A truncated fixture would let every other assertion pass vacuously.

    The floor is per venue, not a single total: the total is not a fixed number
    because a sheet's `*skip …*` rows are not prompts and never enter the
    fixture (Chill Zone alone skips 88 of its 208 rows -- sets whose contents
    the card does not print). One sheet failing to parse is the fault this
    guards against, and that shows up as a venue near zero, not as a slightly
    low total.
    """
    assert len(GOLDEN) >= 480
    per_venue = Counter(c['venue'] for c in GOLDEN)
    assert set(per_venue) == VENUES
    assert min(per_venue.values()) >= 100, per_venue


def test_composition_is_byte_identical_to_every_live_venue_prompt():
    for case in GOLDEN:
        assert prompts.compose(case['subject'], name=case['item'],
                               drink=case['drink']) == case['expected'], case['item']


def test_drink_detection_is_byte_identical_for_every_live_section():
    for case in GOLDEN:
        assert prompts.is_drink(case['section']) is case['drink'], case['section']


def test_for_item_uses_the_printed_name_when_there_is_no_subject():
    """A row with no transcribed prompt still gets one -- the printed name and
    nothing more, which is the only claim the card licenses."""
    out = prompts.for_item('Veg Momo', 'Snacks')
    assert out.startswith('Veg Momo,')
    assert 'steamed pleated dumplings' in out
    assert out.endswith(prompts.FOOD_STYLE)


def test_for_item_reads_the_section_for_the_style_block():
    assert prompts.for_item('Black Tea', 'Hot Drinks').endswith(prompts.DRINK_STYLE)
    assert prompts.for_item('Chicken Momo', 'Snacks').endswith(prompts.FOOD_STYLE)


def test_for_item_prefers_an_explicit_subject():
    out = prompts.for_item('Siciliana', 'Pizza', subject='a thin-crust pizza')
    assert out.startswith('a thin-crust pizza')


def test_the_style_block_stays_last():
    """Its negative clauses ("no garnish", "no props") must be the final thing
    the model reads -- that ordering is what the truthfulness work bought."""
    out = prompts.compose('veg momo', name='Veg Momo', drink=False)
    assert out.index('steamed pleated dumplings') < out.index('no garnish')


@pytest.mark.parametrize('name', ['FOOD_STYLE', 'DRINK_STYLE', 'is_drink', 'full_prompt'])
def test_prompt_sheet_still_exposes_what_its_callers_import(name):
    """`generate_item_images`, `review_images` and `build_venue_fixture` all
    reach for these on `prompt_sheet`. The move must be invisible to them."""
    from menu.pipeline import prompt_sheet
    assert hasattr(prompt_sheet, name)
