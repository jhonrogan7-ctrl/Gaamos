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
