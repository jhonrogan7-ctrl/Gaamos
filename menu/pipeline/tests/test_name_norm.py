"""The one place that decides what "the same printed name" means.

A wrong rule here does not fail loudly -- it silently mismatches every menu that
follows, which is why the substring traps this codebase has already been bitten
by twice (`rum` inside `Rumali Roti`, `momo` inside `Pomodoro`) are pinned as
tests rather than trusted to a comment.
"""
from menu.pipeline import name_norm


def test_case_punctuation_and_spacing_collapse_to_one_form():
    assert name_norm.normalize('  Chicken   Chowmein!  ') == 'chicken chowmein'
    assert name_norm.normalize('CHICKEN CHOWMEIN') == 'chicken chowmein'


def test_accents_are_folded_away():
    assert name_norm.normalize('Café Latté') == 'cafe latte'


def test_ampersand_reads_as_the_word():
    assert name_norm.normalize('Hot & Sour Soup') == 'hot and sour soup'
    assert name_norm.normalize('Hot and Sour Soup') == 'hot and sour soup'


def test_the_four_spellings_of_chowmein_are_one_key():
    forms = ['Chow Mein', 'Chowmein', 'CHOW-MIN', 'Chowmin', 'Chaumin']
    assert {name_norm.normalize(f) for f in forms} == {'chowmein'}


def test_momo_spellings_fold_together():
    forms = ['Momo', 'Mo:Mo', 'MO MO', 'Momos']
    assert {name_norm.normalize(f) for f in forms} == {'momo'}


def test_pakoda_spellings_fold_together():
    forms = ['Pakoda', 'Pakauda', 'Pakora']
    assert {name_norm.normalize(f) for f in forms} == {'pakoda'}


def test_a_fold_never_fires_on_a_substring():
    """`Pomodoro` contains `momo` and `Rumali Roti` contains `rum`. Both have
    reached production as bugs in this codebase; neither may fold."""
    assert name_norm.normalize('Pomodoro Pasta') == 'pomodoro pasta'
    assert name_norm.normalize('Rumali Roti') == 'rumali roti'
    assert name_norm.normalize('Chow Mein Hut') == 'chowmein hut'


def test_digits_survive_normalization():
    assert name_norm.normalize('8848 (180 ml)') == '8848 180 ml'


def test_empty_input_is_the_empty_key():
    assert name_norm.normalize('') == ''
    assert name_norm.normalize(None) == ''


def test_a_trailing_parenthetical_is_the_variant():
    assert name_norm.split_variant('Jhol Momo (Veg)') == ('Jhol Momo', 'Veg')
    assert name_norm.split_variant('Ruslan Vodka (Qtr.)') == ('Ruslan Vodka', 'Qtr.')
    assert name_norm.split_variant('8848 (180 ml)') == ('8848', '180 ml')


def test_a_separated_serving_word_is_the_variant():
    assert name_norm.split_variant('Veg Momo - Half') == ('Veg Momo', 'Half')
    assert name_norm.split_variant('Black Tea / Hot') == ('Black Tea', 'Hot')


def test_a_bare_trailing_measure_is_the_variant():
    assert name_norm.split_variant('Ruslan Vodka 60ml') == ('Ruslan Vodka', '60ml')
    assert name_norm.split_variant('Chicken Sekuwa Half') == ('Chicken Sekuwa', 'Half')


def test_a_bare_trailing_word_that_is_part_of_the_dish_is_not_a_variant():
    """`Ice` and `Large` are serving words only where the card brackets or
    separates them. `Lemon Ice` is a dish; splitting it would key it as `Lemon`."""
    assert name_norm.split_variant('Lemon Ice') == ('Lemon Ice', '')
    assert name_norm.split_variant('Chicken Momo') == ('Chicken Momo', '')
    assert name_norm.split_variant('Hot Chocolate') == ('Hot Chocolate', '')


def test_search_form_is_the_normalized_base():
    assert name_norm.search_form('Jhol Mo:Mo (Veg)') == 'jhol momo'
    assert name_norm.search_form('Chow Mein') == 'chowmein'


def test_entry_key_pairs_the_base_with_the_normalized_variant():
    assert name_norm.entry_key('Jhol Momo (Veg)') == ('jhol momo', 'veg')
    assert name_norm.entry_key('Jhol Mo:Mo (Buff)') == ('jhol momo', 'buff')
    assert name_norm.entry_key('Black Tea') == ('black tea', '')


def test_two_proteins_of_one_dish_never_share_an_entry_key():
    """The protein veto is phase 3's job, but the key must not have merged them
    before the matcher gets a chance to look."""
    assert name_norm.entry_key('Steam Momo (Veg)') != name_norm.entry_key('Steam Momo (Buff)')


def test_a_name_with_no_dish_word_takes_it_from_the_section():
    """The Kailash Parbat card prints `Apple` at 250 under MILK SHAKE / LASSI
    and `Apple` at 250 under JUICE. Phase 2 found it; the library already
    holds it as one colliding entry."""
    assert name_norm.search_form('Apple', 'Juice') == 'apple juice'
    assert name_norm.search_form('Apple', 'Milk Shake / Lassi') == 'apple shake'
    assert name_norm.search_form('Apple', 'Juice') != \
        name_norm.search_form('Apple', 'Milk Shake / Lassi')


def test_a_bare_modifier_becomes_a_dish():
    """`ABC`, `Mixed`, `Plain`, `Sweet` are rows whose dish type exists only in
    the section header."""
    assert name_norm.search_form('ABC', 'Juice') == 'abc juice'
    assert name_norm.search_form('Mixed', 'Fresh Fruit Juice') == 'mixed juice'
    assert name_norm.search_form('Plain', 'Lassi / Shake') == 'plain lassi'


def test_a_name_that_already_names_its_dish_is_untouched():
    """This asymmetry is what keeps the 72 cross-venue keys alive: put the
    section IN the key and `Hot Drinks` splits from `Beverages`."""
    assert name_norm.search_form('Black Tea', 'Hot Drinks') == 'black tea'
    assert name_norm.search_form('Black Tea', 'Beverages') == 'black tea'
    assert name_norm.search_form('Black Tea', 'Hot Drinks') == \
        name_norm.search_form('Black Tea', 'Beverages')


def test_a_section_naming_no_dish_completes_nothing():
    """A guess is worse than a bare key: `KAILASH TOUCH` says nothing about
    what the row is."""
    assert name_norm.search_form('Apple', 'Kailash Touch') == 'apple'
    assert name_norm.search_form('Apple', 'Special Menu') == 'apple'
    assert name_norm.search_form('Apple', '') == 'apple'


def test_the_completed_word_is_appended_not_prepended():
    assert name_norm.search_form('Apple', 'Juice') == 'apple juice'


def test_completion_never_doubles_a_word_the_name_already_has():
    assert name_norm.search_form('Juice', 'Fresh Fruit Juice') == 'juice'


def test_the_section_completes_the_base_name_not_the_variant():
    """`Apple (Large)` under JUICE keys as `apple juice` + variant `large`."""
    assert name_norm.entry_key('Apple (Large)', 'Juice') == ('apple juice', 'large')


def test_the_section_argument_is_optional_and_defaults_to_no_completion():
    """Every pre-phase-3 caller keeps working unchanged."""
    assert name_norm.search_form('Apple') == 'apple'
    assert name_norm.entry_key('Apple (Large)') == ('apple', 'large')


def test_the_live_collisions_between_different_dishes_separate():
    """The five same-venue collisions measured on 2026-08-02 whose rows are
    genuinely different dishes. Their printed prices differ where the dishes
    differ -- `Chicken` is 380 as a sandwich and 240 as a chowmein -- which is
    the evidence that these are two products and not one cross-listed row."""
    collisions = [
        ('Apple', 'Juice', 'Milk Shake / Lassi'),
        ('Banana', 'Muesli, Porridge, Corn Flakes', 'Milk Shake / Lassi'),
        ('Papaya', 'Juice', 'Milk Shake / Lassi'),
        ('Chicken', 'Sandwich & Burger', 'Chowmin / Thukpa'),
        ('Veg', 'Sandwich & Burger', 'Chowmin / Thukpa'),
    ]
    for name, section_a, section_b in collisions:
        assert name_norm.search_form(name, section_a) != \
            name_norm.search_form(name, section_b), f'{name} still collides'


def test_apple_separates_three_ways_because_it_is_printed_three_ways():
    """Kailash Parbat prints `Apple` at 250 under three different sections.
    `Muesli, Porridge, Corn Flakes` names a dish too, so all three separate."""
    keys = {name_norm.search_form('Apple', section) for section in
            ('Juice', 'Milk Shake / Lassi', 'Muesli, Porridge, Corn Flakes')}
    assert keys == {'apple juice', 'apple shake', 'apple muesli'}


def test_a_name_that_already_names_its_dish_stays_one_key_across_sections():
    """The other two measured collisions, and why they are NOT bugs.

    `Can Juice` is printed twice at Tranquility Inn -- Soft Drinks and Fresh
    Fruit Juice -- at 180 BOTH times: one product cross-listed in two drink
    sections, which should merge into one entry.

    `Chocolate Pancake` is printed at 280 under Pancakes and 330 under
    Dessert. Those ARE two products, and section completion cannot separate
    them, because the name already names its dish and completion correctly
    declines to fire. This is a known, accepted limit: the two rows share one
    library entry and one photograph. The harm is bounded -- both are
    chocolate pancakes -- which is why it is documented here rather than
    fixed by weakening the guard that protects the 72 cross-venue keys.
    """
    assert name_norm.search_form('Can Juice', 'Soft Drinks') == \
        name_norm.search_form('Can Juice', 'Fresh Fruit Juice')
    assert name_norm.search_form('Chocolate Pancake', 'Pancakes') == \
        name_norm.search_form('Chocolate Pancake', 'Dessert')
