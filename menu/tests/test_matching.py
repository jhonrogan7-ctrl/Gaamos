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


@pytest.mark.django_db
def test_trigram_catches_a_spelling_drift_the_exact_key_misses():
    """`masaala chowmein` vs `masala chowmein` — measured similarity 0.833.

    The drifting word is deliberately neither a protein nor a dish word: drift
    on a protein token is vetoed (see the Task 4 test) and drift on a dish word
    changes what the section completes, so either would test something other
    than layer 2.
    """
    entry = _entry('Masala Chowmein', section='Chowmein')
    company = _company('venue')

    [match] = matching.match_rows(
        [matching.Row(name='Masaala Chowmein', section='Chowmein')],
        company=company)

    assert match.entry_id == entry.pk
    assert match.layer == 'trigram'
    assert 0.0 < match.score < 1.0


@pytest.mark.django_db
def test_a_trigram_candidate_below_the_floor_is_not_returned():
    """Measured similarity 0.077, well under the 0.35 floor. Neither name
    carries a protein and only one carries a head-word, so no veto can fire --
    the floor is the only thing rejecting this, which is what the test is for.
    """
    _entry('Masala Chowmein', section='Chowmein')
    company = _company('venue')

    [match] = matching.match_rows(
        [matching.Row(name='Fruit Salad', section='Salad')], company=company)

    assert match.entry_id is None


@pytest.mark.django_db
def test_a_veto_beats_a_perfect_trigram_score():
    """This is the whole design in one test: the strings are one character
    apart and the answer is still no."""
    _entry('Buff Momo', section='Momo')
    company = _company('venue')

    [match] = matching.match_rows(
        [matching.Row(name='Bufff Momo', section='Momo')], company=company)

    assert match.entry_id is None
    assert match.veto_count == 1


@pytest.mark.django_db
def test_the_vector_layer_finds_synonymy_trigram_cannot_see():
    """`Fresh Lime Soda` and `Lemon Soda` share almost no trigrams."""
    entry = _entry('Lemon Soda', section='Soft Drinks')
    entry.embedding = [1.0] + [0.0] * 1023
    entry.save(update_fields=['embedding'])
    company = _company('venue')

    [match] = matching.match_rows(
        [matching.Row(name='Fresh Lime Soda', section='Soft Drinks')],
        company=company, embedder=lambda text: [1.0] + [0.0] * 1023)

    assert match.entry_id == entry.pk
    assert match.layer == 'vector'


@pytest.mark.django_db
def test_the_vector_layer_switches_itself_off_when_nothing_is_configured():
    """Spec D6: no embed model means the matcher runs layers 0-2 and every
    other layer works without it. No endpoint can block this feature."""
    entry = _entry('Lemon Soda', section='Soft Drinks')
    entry.embedding = [1.0] + [0.0] * 1023
    entry.save(update_fields=['embedding'])
    company = _company('venue')

    [match] = matching.match_rows(
        [matching.Row(name='Fresh Lime Soda', section='Soft Drinks')],
        company=company, embedder=None)

    assert match.entry_id is None


@pytest.mark.django_db
def test_an_entry_with_no_vector_is_simply_not_a_vector_candidate():
    _entry('Lemon Soda', section='Soft Drinks')
    company = _company('venue')

    [match] = matching.match_rows(
        [matching.Row(name='Fresh Lime Soda', section='Soft Drinks')],
        company=company, embedder=lambda text: [1.0] + [0.0] * 1023)

    assert match.entry_id is None


@pytest.mark.django_db
def test_a_candidate_found_by_both_layers_keeps_its_better_score():
    """Trigram scores this pair 0.833; the injected vectors score it 1.0."""
    entry = _entry('Masala Chowmein', section='Chowmein')
    entry.embedding = [1.0] + [0.0] * 1023
    entry.save(update_fields=['embedding'])
    company = _company('venue')

    [match] = matching.match_rows(
        [matching.Row(name='Masaala Chowmein', section='Chowmein')],
        company=company, embedder=lambda text: [1.0] + [0.0] * 1023)

    assert match.entry_id == entry.pk
    assert match.layer == 'vector'
    assert match.score == pytest.approx(1.0, abs=1e-6)


@pytest.mark.django_db
def test_the_exact_layer_short_circuits_and_costs_no_embedding():
    """Cheapest-first is not decoration: an exact key must not spend an API
    call. The embedder raises, so calling it fails the test."""
    entry = _entry('Veg Momo', section='Momo')
    company = _company('venue')

    def _explode(text):
        raise AssertionError('layer 3 ran for a row layer 1 already answered')

    [match] = matching.match_rows(
        [matching.Row(name='Veg Momo', section='Momo')],
        company=company, embedder=_explode)

    assert match.entry_id == entry.pk


@pytest.mark.django_db
def test_the_adjudication_seam_is_offered_the_ambiguous_middle():
    """0.833 sits inside [MID 0.55, HIGH 0.90) — the ambiguous middle by
    construction, which is the only band the seam is offered."""
    entry = _entry('Masala Chowmein', section='Chowmein')
    company = _company('venue')
    seen = []

    def _adjudicate(row, ranked):
        seen.append((row.name, [e.pk for e, _ in ranked]))
        return ranked[0][0].pk

    [match] = matching.match_rows(
        [matching.Row(name='Masaala Chowmein', section='Chowmein')],
        company=company, adjudicate=_adjudicate)

    assert seen == [('Masaala Chowmein', [entry.pk])]
    assert match.entry_id == entry.pk
    assert match.layer == 'adjudicated'
    assert match.decision == 'auto'


@pytest.mark.django_db
def test_the_adjudicator_may_refuse_and_the_row_stays_unmatched():
    _entry('Masala Chowmein', section='Chowmein')
    company = _company('venue')

    [match] = matching.match_rows(
        [matching.Row(name='Masaala Chowmein', section='Chowmein')],
        company=company, adjudicate=lambda row, ranked: None)

    assert match.entry_id is None
    assert match.decision == 'none'
