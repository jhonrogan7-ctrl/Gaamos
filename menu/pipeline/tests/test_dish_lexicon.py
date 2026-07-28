"""What a menu word already denotes, decided once instead of per item.

A lexicon entry is a denotation, never an addition: `momo` means dumpling the
way `masala` means onion-chilli-coriander through the egg. Anything the printed
name does not commit to must not be in here.
"""
from menu.pipeline import dish_lexicon


def test_head_words_are_found_in_the_item_name():
    assert dish_lexicon.head_words("Jhol Momo (Veg)") == ["momo", "jhol"]


def test_head_words_match_whole_tokens_not_substrings():
    """`Momo Platter` is momo; `Pomodoro` must not be."""
    assert dish_lexicon.head_words("Pomodoro Pasta") == []


def test_expand_appends_the_denotation_of_each_head_word():
    out = dish_lexicon.expand("veg jhol momo in broth", "Jhol Momo (Veg)")

    assert out.startswith("veg jhol momo in broth, ")
    assert "steamed pleated dumplings" in out
    assert "in a thin spiced soup" in out


def test_expand_does_not_repeat_a_denotation_already_in_the_prompt():
    out = dish_lexicon.expand("steamed pleated dumplings", "Veg Momo")

    assert out.count("steamed pleated dumplings") == 1


def test_expand_leaves_an_unknown_name_untouched():
    assert dish_lexicon.expand("a plate of siciliana", "Siciliana") == \
        "a plate of siciliana"


def test_temperature_applies_in_drink_sections_only():
    """`Hot & Sour Soup` is not a hot beverage; `Hot Chocolate` is."""
    soup = dish_lexicon.expand("a bowl of hot and sour soup", "Hot & Sour Soup",
                               drink=False)
    drink = dish_lexicon.expand("a mug of hot chocolate", "Hot Chocolate",
                                drink=True)

    assert "steam" not in soup
    assert "steam" in drink


def test_ice_denotes_a_cold_serving():
    out = dish_lexicon.expand("an americano", "Organic Americano (Ice)",
                              drink=True)

    assert "ice" in out.lower()


def test_needs_definition_flags_a_generatable_row_with_no_known_word_and_no_description():
    row = {"item": "Siciliana", "description": "", "generatable": True,
           "drink": False}

    assert dish_lexicon.needs_definition(row) is True


def test_a_described_row_never_needs_definition():
    """A printed description tells the generator what the dish is; the lexicon
    is only needed when the name has to carry the whole load."""
    row = {"item": "Siciliana", "description": "Tomato, basil, mozzarella.",
           "generatable": True, "drink": False}

    assert dish_lexicon.needs_definition(row) is False


def test_a_skip_row_never_needs_definition():
    row = {"item": "Extra Coil", "description": "", "generatable": False,
           "drink": False}

    assert dish_lexicon.needs_definition(row) is False


def test_no_lexicon_entry_asserts_a_quantity():
    """Counts come from the printed card, never from a word's denotation."""
    banned = ("two ", "three ", "four ", "pieces", "pcs")
    for word, denotation in {**dish_lexicon.LEXICON,
                             **dish_lexicon.DRINK_LEXICON}.items():
        for token in banned:
            assert token not in denotation.lower(), (word, denotation)


def test_a_food_sense_denotation_never_applies_to_a_drink():
    """`masala` on a plate is chopped onion, chilli and coriander. Asserted of
    masala tea it puts onion in the glass — and the card does not print what
    spices the chai holds, so nothing replaces it."""
    assert 'masala' not in dish_lexicon.head_words('Masala Tea', drink=True)
    assert dish_lexicon.expand('a glass of masala tea', 'Masala Tea',
                               drink=True) == 'a glass of masala tea'


def test_the_same_word_still_carries_its_denotation_on_a_plate():
    assert 'chopped onion' in dish_lexicon.expand('a masala omelette',
                                                  'Masala Omelette')


def test_a_beverage_denotation_in_the_dish_lexicon_still_reaches_a_drink():
    """`lassi` lives in LEXICON but already denotes a drink, so a drink section
    must keep it — the food-only exclusion is not a blanket one."""
    out = dish_lexicon.expand('a glass of sweet lassi', 'Sweet Lassi',
                              drink=True)

    assert 'thick yoghurt drink' in out


def test_expand_does_not_repeat_a_denotation_shared_by_two_head_words():
    """`roti` and `chapati` are separate head-words that denote the same
    flatbread. Both appearing in the name must not append the phrase twice."""
    out = dish_lexicon.expand('one roti chapati on a plate', 'Roti (Chapati) per pcs')

    assert out.count('flat round unleavened flatbread') == 1


def test_a_filling_is_not_drawn_outside_the_wrapper_that_encloses_it():
    """A paneer momo's cheese is inside the pleated wrapper, so appending
    `paneer`'s denotation would plate loose cubes beside the dumpling. Chicken
    Momo escaped this only because `chicken` is not a lexicon word — the card
    commits to no more of a paneer momo's appearance than of a chicken one."""
    out = dish_lexicon.expand('a plate of steamed pleated dumplings',
                              'Paneer Momo')

    assert 'cubes of white paneer cheese' not in out
    assert 'paneer' not in dish_lexicon.head_words('Paneer Momo')


def test_the_wrapper_itself_is_still_denoted():
    """Scoping the filling out must not cost the dish its own form."""
    assert 'momo' in dish_lexicon.head_words('Paneer Momo')
    assert 'steamed pleated dumplings' in dish_lexicon.expand('a plate of momo',
                                                              'Paneer Momo')


def test_paneer_still_denotes_itself_where_it_is_visible():
    """The exclusion is scoped to the enclosing dish, not to the word."""
    assert 'cubes of white paneer cheese' in dish_lexicon.expand(
        'paneer in spinach gravy', 'Palak Paneer')


def test_a_cooking_style_that_restates_the_form_replaces_it():
    """Kothe momo is pan-fried. Left to `momo` alone every Kothe row is drawn
    as a plain steamed dumpling — the wrong dish, priced as the right one."""
    out = dish_lexicon.expand('veg kothe momo', 'Kothe Momo (Veg)')

    assert 'seared' in out and 'crisp' in out
    assert 'steamed pleated dumplings' not in out


def test_no_lexicon_entry_uses_the_word_the_generator_declines():
    """`fried` is content-filtered deterministically, and a denotation reaches
    every row carrying its head-word — one bad phrase silently costs a whole
    style its images."""
    for word, denotation in dish_lexicon.LEXICON.items():
        assert 'fried' not in denotation, word


def test_the_restated_form_still_says_what_the_dish_is():
    """Dropping momo's denotation must not cost the row the dumpling itself."""
    out = dish_lexicon.expand('veg kothe momo', 'Kothe Momo (Veg)')

    assert 'pleated dumplings' in out


def test_a_plain_momo_is_still_steamed():
    """The replacement is scoped to the style word, not to momo."""
    assert 'steamed pleated dumplings' in dish_lexicon.expand(
        'veg momo', 'Steam Momo (Veg)')


def test_chilli_denotes_the_sauce_it_is_tossed_in():
    """`Chilli` on a Nepali card is the Indo-Chinese preparation, not a garnish.
    Five Pokhara Metro rows depend on it — three momo plus chicken and paneer."""
    for name in ['Chilli Momo (Veg)', 'Chicken Chilli', 'Paneer Chilli']:
        assert 'chilli sauce' in dish_lexicon.expand('the dish', name), name


def test_the_english_and_nepali_card_spellings_of_chilli_agree():
    """Cards print both `chilly` and `chilli`; a venue's spelling must not
    decide whether the sauce is drawn."""
    assert (dish_lexicon.expand('momo', 'Chilly Momo')
            == dish_lexicon.expand('momo', 'Chilli Momo'))


def test_shakshuka_denotes_eggs_poached_in_tomato_sauce():
    out = dish_lexicon.expand('shakshuka', 'Shakshuka')

    assert 'poached' in out and 'tomato' in out


def test_shakshuka_no_longer_needs_a_definition():
    row = {'generatable': True, 'description': '', 'item': 'Shakshuka',
           'drink': False}

    assert not dish_lexicon.needs_definition(row)
