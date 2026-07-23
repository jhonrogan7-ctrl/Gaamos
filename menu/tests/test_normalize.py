"""Validators for the canonical menu-item model.

Pure functions: no database, no network, no API calls. These tests are the
contract — prompts drift between model versions, these rules do not.
"""
from menu.dietary import DIETARY_VOCAB
from menu.pipeline import normalize


class TestCleanTags:
    """D6: tags come from the printed item name ONLY. The model may split that
    name into words; it may never add a synonym, translation or inferred
    ingredient of its own."""

    def test_keeps_words_present_in_the_printed_name(self):
        assert normalize.clean_tags(['veg', 'chowmein'], 'Veg. Chowmein') == ['veg', 'chowmein']

    def test_drops_invented_synonyms(self):
        # 'momo' and 'dumpling' are not words in 'Veg Mo:Mo' — the model added them.
        assert normalize.clean_tags(['veg', 'momo', 'dumpling'], 'Veg Mo:Mo') == ['veg']

    def test_ignores_case_and_punctuation(self):
        assert normalize.clean_tags(['VEG', 'mo:mo'], 'Veg. Mo:Mo') == ['veg', 'mo:mo']

    def test_keeps_multiword_tag_when_every_word_is_in_the_name(self):
        assert normalize.clean_tags(['black tea'], 'Black Tea') == ['black tea']

    def test_drops_multiword_tag_when_any_word_is_absent(self):
        assert normalize.clean_tags(['black coffee'], 'Black Tea') == []

    def test_deduplicates(self):
        assert normalize.clean_tags(['veg', 'VEG', 'veg'], 'Veg Momo') == ['veg']

    def test_drops_blank_and_punctuation_only_tags(self):
        assert normalize.clean_tags(['', '   ', '!!!'], 'Veg Momo') == []

    def test_handles_none(self):
        assert normalize.clean_tags(None, 'Veg Momo') == []


class TestCleanDietary:
    """D7: a fixed vocabulary, so the guest menu can offer a real filter."""

    def test_vocabulary_distinguishes_buff_and_pork(self):
        # Commercially and religiously significant in this market.
        assert 'buff' in DIETARY_VOCAB
        assert 'pork' in DIETARY_VOCAB

    def test_keeps_known_values(self):
        assert normalize.clean_dietary(['veg', 'buff']) == ['veg', 'buff']

    def test_lowercases(self):
        assert normalize.clean_dietary(['Chicken']) == ['chicken']

    def test_drops_unknown_values(self):
        assert normalize.clean_dietary(['non-veg', 'NONVEG', 'halal']) == []

    def test_deduplicates(self):
        assert normalize.clean_dietary(['veg', 'Veg']) == ['veg']

    def test_handles_none(self):
        assert normalize.clean_dietary(None) == []


class TestCleanPrice:
    """A non-negative int or None. Never coerced from a string — '1,600' is a
    price we did not understand, and guessing is worse than flagging."""

    def test_keeps_non_negative_int(self):
        assert normalize.clean_price(50) == 50
        assert normalize.clean_price(0) == 0

    def test_accepts_integral_float(self):
        assert normalize.clean_price(50.0) == 50

    def test_rejects_fractional_float(self):
        assert normalize.clean_price(50.5) is None

    def test_rejects_strings(self):
        assert normalize.clean_price('50') is None
        assert normalize.clean_price('1,600') is None

    def test_rejects_negative(self):
        assert normalize.clean_price(-5) is None

    def test_rejects_bool(self):
        # bool is a subclass of int; True must not become price 1.
        assert normalize.clean_price(True) is None

    def test_handles_none(self):
        assert normalize.clean_price(None) is None


class TestCleanCurrency:
    def test_uppercases_a_three_letter_code(self):
        assert normalize.clean_currency('usd') == 'USD'

    def test_keeps_npr(self):
        assert normalize.clean_currency('NPR') == 'NPR'

    def test_falls_back_to_npr(self):
        assert normalize.clean_currency('') == 'NPR'
        assert normalize.clean_currency(None) == 'NPR'
        assert normalize.clean_currency('Rs.') == 'NPR'
        assert normalize.clean_currency('RS') == 'NPR'
