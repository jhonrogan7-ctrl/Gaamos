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
