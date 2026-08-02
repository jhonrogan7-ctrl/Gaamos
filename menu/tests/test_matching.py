"""Finding the library entry that is the same dish.

The vetoes are the point of this module, not the scores. A wrong score costs a
click; a wrong veto decision puts a buffalo photograph on a vegetarian row.
"""
import pytest

from menu import matching
from menu.models import Company, Item


def _entry(name, *, section='', use_count=1, shareable=True, company=None,
           image_asset=None, status='active'):
    from menu.pipeline import name_norm
    search_name, variant = name_norm.entry_key(name, section)
    return Item.objects.create(
        name=name, category=section, search_name=search_name,
        variant_label=variant, status=status, use_count=use_count,
        shareable=shareable, origin_company=company, image_asset=image_asset,
        image_prompt='x')


def _company(slug):
    return Company.objects.create(name=slug, slug=slug)


@pytest.mark.django_db
def test_an_exact_key_matches_and_is_auto_accepted():
    _entry('Veg Momo', section='Momo')
    company = _company('venue')

    [match] = matching.match_rows(
        [matching.Row(name='Veg Momo', section='Momo')], company=company)

    assert match.entry_id is not None
    assert match.layer == 'exact'
    assert match.score == 1.0
    assert match.decision == 'auto'


@pytest.mark.django_db
def test_a_row_with_no_candidate_at_all_decides_none():
    company = _company('venue')

    [match] = matching.match_rows(
        [matching.Row(name='Veg Momo', section='Momo')], company=company)

    assert match.entry_id is None
    assert match.decision == 'none'
    assert match.layer == ''


@pytest.mark.django_db
def test_the_same_printed_name_in_two_sections_matches_the_right_entry():
    juice = _entry('Apple', section='Juice')
    _entry('Apple', section='Milk Shake / Lassi')
    company = _company('venue')

    [match] = matching.match_rows(
        [matching.Row(name='Apple', section='Fresh Juice')], company=company)

    assert match.entry_id == juice.pk


@pytest.mark.django_db
def test_a_protein_conflict_vetoes_however_close_the_strings():
    assert matching.veto_reason(
        matching.Row(name='Veg Momo', section='Momo'),
        _entry('Buff Momo', section='Momo')) == 'protein'


@pytest.mark.django_db
def test_an_unqualified_name_never_crosses_a_named_protein():
    """Founder decision 2026-08-02: absence counts as disagreement. Printed
    `Momo` must not inherit `Buff Momo`'s photograph. Blank beats wrong."""
    assert matching.veto_reason(
        matching.Row(name='Momo', section='Momo'),
        _entry('Buff Momo', section='Momo')) == 'protein'


@pytest.mark.django_db
def test_a_protein_spelled_differently_is_not_a_conflict():
    assert matching.veto_reason(
        matching.Row(name='Veg Momo', section='Momo'),
        _entry('Vegetable Momo', section='Momo')) is None


@pytest.mark.django_db
def test_a_misspelled_protein_token_is_conservatively_vetoed():
    """`chiken` is not in PROTEINS, so its set is empty and differs from
    `{chicken}`. Measured consequence: `Chiken Sandwich` does NOT match
    `Chicken Sandwich` even though their trigram similarity is 0.737.

    This is the tightened veto behaving exactly as specified, and it is
    recorded here rather than left to be rediscovered as a bug: layer 2 cannot
    recover OCR drift that lands on the protein word itself. Widen PROTEINS
    only when a real card prints the misspelling.
    """
    assert matching.veto_reason(
        matching.Row(name='Chiken Sandwich', section='Sandwich'),
        _entry('Chicken Sandwich', section='Sandwich')) == 'protein'


@pytest.mark.django_db
def test_disagreeing_head_words_veto():
    """`Chicken Chilly` is not `Chicken Chowmein` however close they look."""
    assert matching.veto_reason(
        matching.Row(name='Chicken Chilly', section='Snacks'),
        _entry('Chicken Chowmein', section='Snacks')) == 'head-word'


@pytest.mark.django_db
def test_overlapping_head_words_do_not_veto():
    """`Masala Chowmein` and `Chowmein` share a head-word. Differing is not the
    same as disjoint, and rejecting on any difference would veto every
    qualified dish against its plain form."""
    assert matching.veto_reason(
        matching.Row(name='Masala Chowmein', section='Chowmein'),
        _entry('Chowmein', section='Chowmein')) is None


@pytest.mark.django_db
def test_a_head_word_the_lexicon_does_not_know_cannot_veto():
    assert matching.veto_reason(
        matching.Row(name='Apple Juice', section='Juice'),
        _entry('Orange Juice', section='Juice')) is None


@pytest.mark.django_db
def test_another_venues_unshareable_entry_is_never_a_candidate():
    """A venue's own photograph is its property (spec D2). It matches for that
    venue only and never leaks."""
    owner = _company('owner')
    _entry('Veg Momo', section='Momo', shareable=False, company=owner)
    other = _company('other')

    [match] = matching.match_rows(
        [matching.Row(name='Veg Momo', section='Momo')], company=other)

    assert match.entry_id is None


@pytest.mark.django_db
def test_a_venues_own_unshareable_entry_matches_for_that_venue():
    owner = _company('owner')
    entry = _entry('Veg Momo', section='Momo', shareable=False, company=owner)

    [match] = matching.match_rows(
        [matching.Row(name='Veg Momo', section='Momo')], company=owner)

    assert match.entry_id == entry.pk


@pytest.mark.django_db
def test_a_merged_or_rejected_entry_is_never_a_candidate():
    _entry('Veg Momo', section='Momo', status='merged')
    company = _company('venue')

    [match] = matching.match_rows(
        [matching.Row(name='Veg Momo', section='Momo')], company=company)

    assert match.entry_id is None


@pytest.mark.django_db
def test_the_entry_more_venues_serve_wins_a_tie():
    """The tea four venues pour outranks a one-off with the same key."""
    _entry('Black Tea', section='Hot Drinks', use_count=1)
    popular = _entry('Black Tea', section='Beverages', use_count=4)
    company = _company('venue')

    [match] = matching.match_rows(
        [matching.Row(name='Black Tea', section='Hot Drinks')], company=company)

    assert match.entry_id == popular.pk


@pytest.mark.django_db
def test_index_text_is_one_function_so_query_and_passage_cannot_drift():
    assert matching.index_text('Apple', 'Juice') == 'Apple — Juice'
    assert matching.index_text('Apple', '') == 'Apple'
