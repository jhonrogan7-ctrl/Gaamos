"""Measure the matcher against a venue the library has not been told about.

    python manage.py match_report --holdout chillzone [--sweep]

Reports, in this order: FALSE MATCHES, then hit rate, then the size of the
ambiguous middle.

That order is the point. The truth set is derived from the backfill's own
keying, so layer 1 finds it by construction and the hit rate is close to
tautological -- it will read impressively for no reason at all. What carries
information is how often layers 2 and 3 hand a confident answer to a row that
has no counterpart in the library, because that is the one that reaches a
paying guest as a wrong photograph.

The library is NOT rebuilt to run this. Entries the holdout venue alone
contributed are excluded from the candidate pool, which is the same set as a
rebuild would produce and costs one query filter instead of a destructive
re-derivation of 517 rows.
"""
from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError

from menu import library, matching
from menu.models import Company, Item, MenuItem
from menu.pipeline import name_norm


@dataclass
class Tally:
    rows: int = 0
    hits: int = 0
    misses: int = 0
    false_matches: int = 0
    correct_abstentions: int = 0
    ambiguous: int = 0
    vetoed: int = 0


def pool_without(holdout):
    """Every entry a library that had never seen `holdout` would hold.

    `use_count` is the number of venues serving an entry, SET from the run
    rather than incremented (phase 1), so `origin=holdout, use_count=1` is
    exactly the set no other venue contributed to. An entry the holdout shares
    with somebody else stays: removing it would understate what the library
    genuinely knows.
    """
    return Item.objects.filter(status='active').exclude(
        origin_company=holdout, use_count=1)


def rows_for(company):
    """The holdout's printed menu, as the matcher would receive it."""
    rows = []
    for menu_item in MenuItem.all_objects.filter(company=company).order_by('slug'):
        section = library._section(menu_item)
        if not section:
            continue
        rows.append(matching.Row(name=menu_item.name, section=section,
                                 dietary_tags=tuple(menu_item.dietary_tags or [])))
    return rows


def truth_for(row, pool):
    """The entry this row genuinely is, or None.

    Genuine identity here is the key the backfill would have derived -- which
    is why layer 1's hit rate against this is not evidence of anything.
    """
    search_name, variant = name_norm.entry_key(row.name, row.section)
    for entry in pool:
        if entry.search_name == search_name and \
                name_norm.normalize(entry.variant_label) == variant:
            return entry
    return None


def score(matches, truths):
    """Tally a run. `truths` maps a row's index to its true entry id or None."""
    tally = Tally(rows=len(matches))
    for index, match in enumerate(matches):
        truth = truths.get(index)
        tally.vetoed += match.veto_count
        if match.decision == 'suggested':
            tally.ambiguous += 1
        if match.entry_id is None:
            if truth is None:
                tally.correct_abstentions += 1
            else:
                tally.misses += 1
        elif truth is not None and match.entry_id == truth:
            tally.hits += 1
        else:
            # Both a confident answer where none was warranted and a confident
            # answer that names the wrong entry. They are one failure from the
            # guest's side: a photograph of something else.
            tally.false_matches += 1
    return tally


class Command(BaseCommand):
    help = ('Measure the matcher over one venue against a library that venue '
            'did not contribute to.')

    def add_arguments(self, parser):
        parser.add_argument('--holdout', required=True,
                            help='Company slug to measure. Its own one-off '
                                 'library entries are excluded from the pool.')
        parser.add_argument('--sweep', action='store_true',
                            help='Re-tally at a range of high/mid thresholds.')
        parser.add_argument('--limit', type=int, default=0,
                            help='Measure only the first N rows (a smoke run; '
                                 'layer 3 costs one API call per row).')

    def handle(self, *args, **opts):
        company = Company.objects.filter(slug=opts['holdout']).first()
        if company is None:
            raise CommandError(f'No company with slug {opts["holdout"]!r}.')

        pool_qs = pool_without(company)
        pool = list(pool_qs)
        rows = rows_for(company)
        if opts['limit']:
            rows = rows[:opts['limit']]
        truths = {}
        for index, row in enumerate(rows):
            entry = truth_for(row, pool)
            truths[index] = entry.pk if entry else None

        # `pool_qs`, not `pool`: the matcher's own layers filter/annotate a
        # QuerySet (`_exact`, `_trigram`, `_vector`), and it must see the same
        # restricted set `truth_for` was scored against -- otherwise the
        # matcher can hand back an entry the truth set was built to exclude,
        # which the scorer would then book as a false match on a row that was
        # in fact matched correctly (defect #14).
        matches = matching.match_rows(rows, company=company, pool=pool_qs)
        tally = score(matches, truths)
        self._report(company, pool, tally, matches, truths)

        if opts['sweep']:
            self._sweep(matches, truths)

    def _report(self, company, pool, tally, matches, truths):
        have_truth = sum(1 for t in truths.values() if t is not None)
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'{company.slug}: {tally.rows} rows against {len(pool)} entries '
            f'({have_truth} rows have a true counterpart)'))
        style = self.style.ERROR if tally.false_matches else self.style.SUCCESS
        self.stdout.write(style(
            f'FALSE MATCHES {tally.false_matches}'
            f'  ({tally.false_matches / max(1, tally.rows):.1%} of rows)'))
        self.stdout.write(
            f'hits {tally.hits} | misses {tally.misses} | '
            f'correct abstentions {tally.correct_abstentions}')
        self.stdout.write(self.style.WARNING(
            f'ambiguous middle {tally.ambiguous} rows — this is the number '
            f'that decides whether layer 4 is ever built'))
        self.stdout.write(f'candidates refused by a veto: {tally.vetoed}')
        by_layer = {}
        for match in matches:
            if match.entry_id is not None:
                by_layer[match.layer] = by_layer.get(match.layer, 0) + 1
        self.stdout.write('matched by layer: ' + (
            ' | '.join(f'{k} {v}' for k, v in sorted(by_layer.items())) or 'none'))
        for index, match in enumerate(matches):
            truth = truths.get(index)
            if match.entry_id is not None and match.entry_id != truth:
                entry = Item.objects.get(pk=match.entry_id)
                self.stdout.write(self.style.ERROR(
                    f'  ✗ {match.row.name!r} [{match.row.section}] '
                    f'-> #{entry.pk} {entry.name!r} [{entry.category}] '
                    f'{match.layer} {match.score:.2f}'))

    def _sweep(self, matches, truths):
        """Re-decide at other thresholds without re-running the layers.

        Only the decision boundary moves, so the expensive part -- the queries
        and the embeddings -- is not repeated.
        """
        self.stdout.write(self.style.MIGRATE_HEADING('threshold sweep'))
        self.stdout.write('  high   mid   false  hits  ambiguous')
        for high in (0.98, 0.95, 0.90, 0.85):
            for mid in (0.75, 0.65, 0.55, 0.45):
                if mid >= high:
                    continue
                redecided = []
                for m in matches:
                    if m.entry_id is None:
                        redecided.append(m)
                        continue
                    decision = matching._decide(m.score, high, mid)
                    if decision == 'none':
                        # Below the new floor this row is not matched at all,
                        # so it must lose its entry too -- keeping the id while
                        # deciding `none` would score as a match it isn't.
                        redecided.append(
                            matching.Match(row=m.row, veto_count=m.veto_count))
                    else:
                        redecided.append(matching.Match(
                            row=m.row, entry_id=m.entry_id, score=m.score,
                            layer=m.layer, veto_count=m.veto_count,
                            decision=decision))
                tally = score(redecided, truths)
                self.stdout.write(
                    f'  {high:.2f}  {mid:.2f}  {tally.false_matches:5}  '
                    f'{tally.hits:4}  {tally.ambiguous:9}')
