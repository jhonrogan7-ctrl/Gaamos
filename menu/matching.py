"""Find the library entry that is the same dish as a printed row.

Layered cheapest-first (spec §4): an exact key, a trigram index, a vector
search, and an adjudication seam that ships unfilled. Every layer is optional
except the exact one -- with every endpoint dead the matcher still runs and the
wizard still works with fewer matches.

The VETOES are what this module is for. A similarity score is a suggestion; a
veto is a refusal, and it wins against any number. Handing a Veg row a Buff
photograph is a religious and dietary violation that reaches a guest, not a
picture somebody dislikes -- so the protein veto fires on ANY disagreement
including absence (founder, 2026-08-02): printed `Momo` matches only `Momo`.

An unmatched row is not a failure. It falls through to generation from its own
printed name, which is the safe outcome. Blank beats wrong.
"""
from dataclasses import dataclass

from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import Q
from pgvector.django import CosineDistance

from menu.models import Item
from menu.pipeline import dish_lexicon, dish_words, name_norm, prompts


@dataclass(frozen=True)
class Row:
    """One printed menu row, as the extractor read it.

    Deliberately not a model: phase 4's `MenuBuildRow` does not exist yet, the
    harness feeds this from tenant `MenuItem`s, and a matcher that could only
    be called with a database row could not be tested without one.
    """
    name: str
    section: str = ''
    dietary_tags: tuple = ()


@dataclass(frozen=True)
class Match:
    row: Row
    entry_id: int = None
    score: float = 0.0
    layer: str = ''          # 'exact' | 'trigram' | 'vector' | 'adjudicated'
    decision: str = 'none'   # 'auto' | 'suggested' | 'none'
    veto_count: int = 0      # candidates a veto refused, for the report


def _thresholds():
    from django.conf import settings
    return settings.MENU_MATCH_HIGH, settings.MENU_MATCH_MID


def index_text(name, section):
    """The text BOTH sides embed -- a stored entry as `passage`, an incoming
    row as `query`.

    One function on purpose. The two calls happen in different modules on
    different days, and a query embedded from a different string than the
    passage is a silent accuracy loss with no failing test anywhere.
    """
    return f'{name} — {section}' if section else name


def candidates_for(company):
    """Every library entry this company is allowed to match against.

    A venue-supplied photograph is `shareable=False` and belongs to the venue
    that supplied it (spec D2). Scoped in the query rather than filtered after,
    so no code path can forget it.
    """
    return Item.objects.filter(status='active').filter(
        Q(shareable=True) | Q(origin_company=company))


def veto_reason(row, entry):
    """Why this entry may not match this row, or None.

    Returns a string rather than a bool so the harness can report which veto
    fired and how often -- a veto that never fires is dead code and one that
    fires constantly is miscalibrated, and neither is visible from a hit rate.
    """
    if dish_words.proteins(row.name) != dish_words.proteins(entry.name):
        return 'protein'
    row_heads = set(dish_lexicon.head_words(
        row.name, drink=prompts.is_drink(row.section)))
    entry_heads = set(dish_lexicon.head_words(
        entry.name, drink=prompts.is_drink(entry.category)))
    # Disjoint, not merely different: `Masala Chowmein` and `Chowmein` share a
    # head-word and are plainly the same dish. Only a total disagreement --
    # `Chicken Chilly` against `Chicken Chowmein` -- is a refusal.
    if row_heads and entry_heads and row_heads.isdisjoint(entry_heads):
        return 'head-word'
    return None


def _rank(scored):
    """Best candidate first: score, then how many venues serve it, then whether
    it can actually supply a picture."""
    return sorted(scored, key=lambda s: (-s[1], -s[0].use_count,
                                         s[0].image_asset_id is None, s[0].pk))


def _exact(row, pool):
    """Layer 1 -- exact on (search_name, variant_label). Near-certain, free.

    The stored `variant_label` is the printed text, not a normalized form, so
    it is compared through `normalize` here rather than in the query.
    """
    search_name, variant = name_norm.entry_key(row.name, row.section)
    return [e for e in pool.filter(search_name=search_name)
            if name_norm.normalize(e.variant_label) == variant]


def _decide(score, high, mid):
    if score >= high:
        return 'auto'
    if score >= mid:
        return 'suggested'
    return 'none'


# Layers whose winning candidate may reach a guest with no human in the loop.
#
# Measured on two held-out venues (2026-08-02): layers 2 (trigram) and 3
# (vector) produced zero verifiable correct matches and every wrong one,
# including `Blue Diamond (60 ml)` [Gin] -> `Fanta (180ml)` at cosine 0.71 and
# `Absolut` -> `Fanta` at 0.74 -- both comfortably clearing `MENU_MATCH_HIGH`.
# Cosine on `nv-embedqa-e5-v5` is compressed into a band where unrelated items
# score high, so a vector score cannot share a threshold scale with a trigram
# or exact score. Layer 1 (exact key) had perfect precision across the same
# run, so it alone may auto-apply.
#
# Founder decision, 2026-08-02: a wrong fuzzy match must cost one human click
# at the review gate, not put a Fanta photograph on a gin row on a paying
# guest's menu. Blank beats wrong. Do not "simplify" this back to a string
# comparison inline in `_best` -- the named set is what stops a future editor
# from re-deriving the Fanta bug by treating the cap as redundant with
# `_decide`.
#
# `adjudicated` IS in this set on purpose: layer 4 is not built (`adjudicate`
# ships as `None` below), and a text model explicitly affirming "same dish" is
# a second opinion in a way a raw similarity score is not. Whether an
# adjudicated match may auto-apply is a separate founder call if layer 4 is
# ever built -- it is not decided by this measurement.
AUTO_LAYERS = frozenset({'exact', 'adjudicated'})


CANDIDATE_LIMIT = 10

# `None` is a meaningful value for `embedder` (force layer 3 off), so
# `match_rows` needs a distinct sentinel to mean "not supplied -- resolve the
# configured provider".
_UNSET = object()


def _trigram(row, pool):
    """Layer 2 -- `pg_trgm` over the GIN index phase 1's migration 0019 built.

    Catches OCR noise, spacing and spelling drift. Still zero API calls.
    """
    from django.conf import settings
    search_name, _ = name_norm.entry_key(row.name, row.section)
    if not search_name:
        return []
    hits = (pool.annotate(sim=TrigramSimilarity('search_name', search_name))
            .filter(sim__gte=settings.MENU_MATCH_TRIGRAM_FLOOR)
            .order_by('-sim')[:CANDIDATE_LIMIT])
    return [(entry, float(entry.sim)) for entry in hits]


def _vector(row, pool, embedder):
    """Layer 3 -- cosine over `Item.embedding`, or nothing at all.

    Earns its place on synonymy trigram cannot see: `Fresh Lime Soda` and
    `Lemon Soda` are the same drink and share almost no trigrams.

    Returns [] when no embedder is configured, which is spec D6 in one line --
    a dead endpoint switches this layer off rather than breaking the matcher.
    The row is a `query` and a stored entry is a `passage`; that asymmetry is
    why `nv-embedqa-e5-v5` was chosen, and `item_embed` owns it.
    """
    if embedder is None:
        return []
    vector = embedder(index_text(row.name, row.section))
    if vector is None:
        return []
    hits = (pool.exclude(embedding=None)
            .annotate(distance=CosineDistance('embedding', vector))
            .order_by('distance')[:CANDIDATE_LIMIT])
    return [(entry, 1.0 - float(entry.distance)) for entry in hits]


def match_rows(rows, *, company, adjudicate=None, embedder=_UNSET, pool=None):
    """-> one `Match` per row, in order.

    `adjudicate` is the layer-4 seam: a callable taking (row, [(entry, score)])
    and returning an entry id or None. It ships as None -- phase 3 measures how
    many rows land in the ambiguous middle before deciding whether a text model
    belongs there at all. No `rerank_nv` module exists, because no reranking
    model exists on this account and an empty module claims one might.

    `embedder` is layer 3's seam and defaults to the configured catalog
    embedder. Pass None to force the vector layer off; pass a callable in tests
    so the suite never reaches an endpoint.

    `pool` is the candidate-set seam: pass a restricted queryset to search a
    library smaller than `company` would normally see -- the accuracy harness
    uses it to measure against a library that has never heard of the venue
    under test, which `candidates_for` alone cannot do because it always
    admits a company's own entries. Production leaves this `None` and gets
    `candidates_for(company)`, unchanged.
    """
    if embedder is _UNSET:
        from menu.pipeline import item_embed
        embedder = item_embed.resolve_provider()
    high, mid = _thresholds()
    pool = candidates_for(company) if pool is None else pool
    out = []
    for row in rows:
        vetoed = 0
        seen = {}
        exact = _exact(row, pool)
        if exact:
            found = [(entry, 1.0, 'exact') for entry in exact]
        else:
            # Cheapest-first is a cost decision, not a style: layer 3 spends an
            # API call per row and must not run for a row layer 1 answered.
            found = [(entry, score, 'trigram')
                     for entry, score in _trigram(row, pool)]
            found += [(entry, score, 'vector')
                      for entry, score in _vector(row, pool, embedder)]
        for entry, score, layer in found:
            if veto_reason(row, entry):
                vetoed += 1
                continue
            # A candidate both layers found keeps its better score.
            if entry.pk not in seen or score > seen[entry.pk][1]:
                seen[entry.pk] = (entry, score, layer)
        scored = list(seen.values())
        out.append(_best(row, scored, vetoed, high, mid, adjudicate))
    return out


def _best(row, scored, vetoed, high, mid, adjudicate):
    if not scored:
        return Match(row=row, veto_count=vetoed)
    ranked = _rank([(entry, score) for entry, score, _ in scored])
    layers = {entry.pk: layer for entry, _, layer in scored}
    entry, score = ranked[0]
    decision = _decide(score, high, mid)
    if decision == 'suggested' and adjudicate is not None:
        chosen = adjudicate(row, ranked[:5])
        if chosen is None:
            return Match(row=row, veto_count=vetoed)
        entry = next(e for e, _ in ranked if e.pk == chosen)
        return Match(row=row, entry_id=entry.pk, score=score,
                     layer='adjudicated', decision='auto', veto_count=vetoed)
    if decision == 'none':
        return Match(row=row, veto_count=vetoed)
    layer = layers[entry.pk]
    if decision == 'auto' and layer not in AUTO_LAYERS:
        # Demote only. A trigram/vector score that cleared `high` is still a
        # confident-sounding number, but confidence from these two layers has
        # been measured wrong 100% of the time it was checked -- see
        # `AUTO_LAYERS`. `suggested` still reaches the review gate; it just
        # never skips it. This must never run for `decision == 'none'`, which
        # is why it is gated on `== 'auto'` rather than `!= 'none'`.
        decision = 'suggested'
    return Match(row=row, entry_id=entry.pk, score=score,
                 layer=layer, decision=decision, veto_count=vetoed)
