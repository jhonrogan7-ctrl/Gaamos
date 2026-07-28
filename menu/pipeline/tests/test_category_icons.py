"""Which icon a printed section name already implies.

The rule that matters most here is the one this repo has already broken once:
match whole tokens, never substrings. `rum` sits inside `Rumali Roti` and `gin`
inside `Ginger Chicken`, and a substring match plated spirits as food.
"""
from menu.pipeline import category_icons
from menu.tests.icons_js import defined_icon_keys


def test_a_plain_section_name_maps_to_its_icon():
    assert category_icons.for_section('Momo') == 'momo'
    assert category_icons.for_section('Paneer') == 'paneer'
    assert category_icons.for_section('Rice') == 'rice'


def test_matching_is_by_token_not_substring():
    """The Chill Zone bug: `rum` inside Rumali Roti, `gin` inside Ginger Chicken."""
    assert category_icons.for_section('Rumali Roti') != 'subSpirits'
    assert category_icons.for_section('Ginger Chicken') != 'subSpirits'
    assert category_icons.for_section('Rum') == 'subSpirits'
    assert category_icons.for_section('Gin') == 'subSpirits'


def test_a_collapsed_name_resolves():
    """`Mo:Mo` slugifies to `mo-mo`, whose tokens are useless; the collapsed
    form `momo` is what carries it."""
    assert category_icons.for_section('Mo:Mo') == 'momo'
    assert category_icons.for_section('MO : MO') == 'momo'


def test_plurals_need_no_duplicate_entries():
    assert category_icons.for_section('Soups') == 'subSoup'
    assert category_icons.for_section('Salads') == 'subSalad'
    assert category_icons.for_section('Toasts') == 'subToast'
    assert category_icons.for_section('Potatoes') == 'potato'
    assert category_icons.for_section('Sandwiches') == 'subSandwich'


def test_a_compound_name_is_not_decided_by_its_generic_half():
    """`Hot Drinks` is coffee, not the generic juice that bare `Drinks` gets."""
    assert category_icons.for_section('Hot Drinks') == 'coffee'
    assert category_icons.for_section('Drinks') == 'juice'
    assert category_icons.for_section('Soft Drinks') == 'subSoda'


def test_priority_is_declaration_order_and_is_stable():
    """`Sandwich & Burger` matches two rules; the earlier one wins, always."""
    assert category_icons.for_section('Sandwich & Burger') == 'subSandwich'
    assert category_icons.for_section('Sandwich and Burger') == 'subSandwich'


def test_an_unrecognised_house_name_falls_back():
    assert category_icons.for_section('Kailash Touch') == 'dish'
    assert category_icons.for_section('After Wake-Up') == 'dish'
    assert category_icons.for_section('') == 'dish'


def test_every_key_the_mapper_can_emit_has_an_svg():
    """A key with no SVG renders as literal text on the guest menu
    (static/js/app.js:176), so a typo here would ship visible garbage."""
    emittable = {icon for _, icon in category_icons.RULES} | {category_icons.FALLBACK}
    assert emittable <= defined_icon_keys()


def test_the_fifteen_metro_sections_all_resolve():
    """The venue this was built for. Named explicitly so a rule reorder that
    breaks one of them fails here rather than on the guest menu."""
    assert [category_icons.for_section(s) for s in (
        'Drinks', 'Breakfast', 'Eggs', 'Cereals', 'Pancakes', 'Sandwiches',
        'Toasts', 'Salads', 'Momo', 'Paneer', 'Potatoes', 'Chicken', 'Soups',
        'Rice', 'Nepali Thali Set')] == [
        'juice', 'brunch', 'subEggs', 'cereal', 'cake', 'subSandwich',
        'subToast', 'subSalad', 'momo', 'paneer', 'potato', 'meat', 'subSoup',
        'rice', 'thali']
