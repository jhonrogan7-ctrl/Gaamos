"""Which tokens name a dish, and which name a protein.

Two rules carry this module. Matching is on whole tokens, because `rum` sits
inside `Rumali Roti` and `gin` inside `Ginger Chicken` and both are real menu
rows. And a protein set is CANONICAL, because `Veg Momo` and `Vegetable Momo`
are one dish while `Veg Momo` and `Buff Momo` are a religious violation.
"""
from menu.pipeline import dish_words


def test_the_first_dish_word_wins_reading_left_to_right():
    assert dish_words.dish_word('Milk Shake / Lassi') == 'shake'
    assert dish_words.dish_word('Chowmin / Thukpa') == 'chowmein'
    assert dish_words.dish_word('Juice') == 'juice'


def test_a_section_naming_no_dish_has_no_dish_word():
    assert dish_words.dish_word('Kailash Touch') == ''
    assert dish_words.dish_word('Special Menu') == ''
    assert dish_words.dish_word('') == ''


def test_a_plural_section_reads_as_its_singular():
    assert dish_words.dish_word('Desserts') == 'dessert'
    assert dish_words.dish_word('Sandwiches') == 'sandwich'
    assert dish_words.dish_word('Soups') == 'soup'


def test_a_dish_word_is_never_matched_inside_a_longer_word():
    """`rum` inside `Rumali Roti` and `gin` inside `Ginger Chicken` are the two
    substring traps this codebase has actually shipped."""
    assert dish_words.dish_word('Rumali Roti') == 'roti'
    assert dish_words.dish_word('Ginger Chicken') == ''
    assert dish_words.dish_word('Rum') == 'rum'


def test_has_dish_word_reports_whether_a_name_identifies_itself():
    assert dish_words.has_dish_word('Chicken Chowmein') is True
    assert dish_words.has_dish_word('Apple') is False
    assert dish_words.has_dish_word('ABC') is False


def test_protein_synonyms_collapse_to_one_canonical_token():
    assert dish_words.proteins('Veg Momo') == dish_words.proteins('Vegetable Momo')
    assert dish_words.proteins('Buff Momo') == dish_words.proteins('Buffalo Momo')
    assert dish_words.proteins('Veg Momo') == frozenset({'veg'})


def test_different_proteins_are_different_sets():
    assert dish_words.proteins('Veg Momo') != dish_words.proteins('Buff Momo')
    assert dish_words.proteins('Chicken Momo') != dish_words.proteins('Pork Momo')


def test_a_name_naming_no_protein_has_an_empty_set():
    """This is what makes the veto fire on absence: an empty set differs from
    every non-empty one, so bare `Momo` never crosses `Buff Momo`."""
    assert dish_words.proteins('Momo') == frozenset()
    assert dish_words.proteins('Momo') != dish_words.proteins('Buff Momo')


def test_a_protein_is_never_matched_inside_a_longer_word():
    assert dish_words.proteins('Vegas Roll') == frozenset()
    assert dish_words.proteins('Chickpea Salad') == frozenset()


def test_a_name_may_carry_several_proteins():
    assert dish_words.proteins('Chicken and Egg Sandwich') == \
        frozenset({'chicken', 'egg'})


def test_punctuation_and_case_do_not_hide_a_token():
    assert dish_words.dish_word('MO:MO') == 'momo'
    assert dish_words.proteins('VEG.') == frozenset({'veg'})


def test_the_spellings_live_cards_actually_print_resolve():
    """`Deserts` and `Shisa (Hukka)` are real category names in this
    platform's own data and neither resolved in the first version of this
    module. A shisha row is a bare flavour name (`Mint`, `Grape`), so failing
    to complete it is precisely the collision section completion exists to
    prevent."""
    assert dish_words.dish_word('Deserts') == 'dessert'
    assert dish_words.dish_word('Shisa (Hukka)') == 'shisha'


def test_a_synonym_is_still_matched_only_as_a_whole_token():
    assert dish_words.dish_word('Deserted Island Platter') == ''
