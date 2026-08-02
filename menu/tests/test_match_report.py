"""The harness's arithmetic.

Whether the matcher is any good is a live measurement, not a test. What is
testable is that the harness counts the right things -- above all that it does
not flatter itself by scoring layer 1 against a truth set layer 1 defined.
"""
import pytest

from menu import matching
from menu.management.commands import match_report
from menu.models import Company, Item


def _entry(name, *, section='', company=None, use_count=1):
    from menu.pipeline import name_norm
    search_name, variant = name_norm.entry_key(name, section)
    return Item.objects.create(
        name=name, category=section, search_name=search_name,
        variant_label=variant, status='active', use_count=use_count,
        origin_company=company, image_prompt='x')


@pytest.mark.django_db
def test_the_holdouts_own_one_off_entries_are_excluded_from_the_pool():
    holdout = Company.objects.create(name='Chill Zone', slug='chillzone')
    own = _entry('House Special', section='Snacks', company=holdout, use_count=1)

    pool = match_report.pool_without(holdout)

    assert own.pk not in {e.pk for e in pool}


@pytest.mark.django_db
def test_an_entry_the_holdout_shares_with_another_venue_stays_in_the_pool():
    """`use_count=2` means a second venue serves it, so it is not the holdout's
    to remove -- removing it would understate what the library really knows."""
    holdout = Company.objects.create(name='Chill Zone', slug='chillzone')
    shared = _entry('Black Tea', section='Hot Drinks', company=holdout,
                    use_count=2)

    pool = match_report.pool_without(holdout)

    assert shared.pk in {e.pk for e in pool}


@pytest.mark.django_db
def test_a_confident_match_on_a_row_with_no_true_counterpart_is_a_false_match():
    """The headline number. This is the failure that reaches a guest."""
    tally = match_report.score(
        [matching.Match(row=matching.Row(name='X'), entry_id=7, score=0.95,
                        layer='trigram', decision='auto')],
        {0: None})

    assert tally.false_matches == 1
    assert tally.hits == 0


@pytest.mark.django_db
def test_declining_to_match_a_row_with_no_counterpart_is_correct_not_a_miss():
    tally = match_report.score(
        [matching.Match(row=matching.Row(name='X'))], {0: None})

    assert tally.false_matches == 0
    assert tally.misses == 0
    assert tally.correct_abstentions == 1


@pytest.mark.django_db
def test_matching_the_wrong_entry_counts_as_a_false_match_not_a_miss():
    tally = match_report.score(
        [matching.Match(row=matching.Row(name='X'), entry_id=7, score=0.95,
                        layer='trigram', decision='auto')],
        {0: 9})

    assert tally.false_matches == 1
    assert tally.hits == 0


@pytest.mark.django_db
def test_the_ambiguous_middle_is_counted_separately():
    """This is the number that decides whether layer 4 is ever built."""
    tally = match_report.score(
        [matching.Match(row=matching.Row(name='X'), entry_id=7, score=0.7,
                        layer='trigram', decision='suggested')],
        {0: 7})

    assert tally.ambiguous == 1
    assert tally.hits == 1
