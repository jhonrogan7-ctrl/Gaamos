"""Which icon a printed section name already implies.

A venue's sections are its own words — `KAILASH TOUCH` stays `KAILASH TOUCH`
(B5) — so nothing here renames anything. It only picks the picture beside the
name, and an icon asserts nothing about the food that the name does not
already say.

Order is priority. The tuple is scanned top to bottom and the first hit wins,
so a compound name is decided by its specific half: `Hot Drinks` is coffee
before it is the generic juice that bare `Drinks` gets. Reordering these lines
changes behaviour, which is why they are a tuple and not a dict.

Every icon named here must exist in `static/js/icons.js` — a key with no SVG
renders as literal text on the guest menu. A test enforces it.
"""
from django.utils.text import slugify

FALLBACK = 'dish'

RULES = (
    # ── Compound names, before the generic word they contain ──────────────
    ('hotdrinks',   'coffee'),
    ('icedcoffee',  'coffee'),
    ('softdrinks',  'subSoda'),
    ('colddrinks',  'subSoda'),
    ('harddrinks',  'subSpirits'),
    ('milkshake',   'smoothie'),
    ('springroll',  'snack'),

    # ── Nepali menu staples ───────────────────────────────────────────────
    ('momo',        'momo'),
    ('thali',       'thali'),
    ('khaja',       'thali'),
    ('paneer',      'paneer'),
    ('pakoda',      'snack'),
    ('sadeko',      'snack'),
    ('thukpa',      'noodles'),
    ('chowmein',    'noodles'),
    ('chowmin',     'noodles'),
    ('biryani',     'rice'),

    # ── Breakfast and cereals ─────────────────────────────────────────────
    ('breakfast',   'brunch'),
    ('brunch',      'brunch'),
    ('cereal',      'cereal'),
    ('muesli',      'cereal'),
    ('porridge',    'cereal'),
    ('cornflake',   'cereal'),
    ('egg',         'subEggs'),
    ('toast',       'subToast'),
    ('pancake',     'cake'),

    # ── Food ──────────────────────────────────────────────────────────────
    ('sandwich',    'subSandwich'),
    ('burger',      'subBurger'),
    ('wrap',        'subWrap'),
    ('pizza',       'pizza'),
    ('pasta',       'subPasta'),
    ('spaghetti',   'subPasta'),
    ('noodle',      'noodles'),
    ('soup',        'subSoup'),
    ('salad',       'subSalad'),
    ('potato',      'potato'),
    ('rice',        'rice'),
    ('chicken',     'meat'),
    ('pork',        'meat'),
    ('buff',        'meat'),
    ('bbq',         'meat'),
    ('meat',        'meat'),
    ('cake',        'cake'),
    ('dessert',     'dessert'),
    ('snack',       'snack'),

    # ── Drinks ────────────────────────────────────────────────────────────
    ('juice',       'juice'),
    ('lassi',       'smoothie'),
    ('shake',       'smoothie'),
    ('smoothie',    'smoothie'),
    ('coffee',      'coffee'),
    ('tea',         'subTea'),
    ('beer',        'subBeer'),
    ('wine',        'subWine'),
    ('cocktail',    'subCocktail'),
    ('whisky',      'subSpirits'),
    ('whiskey',     'subSpirits'),
    ('rum',         'subSpirits'),
    ('vodka',       'subSpirits'),
    ('gin',         'subSpirits'),
    ('brandy',      'subSpirits'),
    ('hookah',      'hookah'),
    ('hukka',       'hookah'),
    ('shisa',       'hookah'),
    ('bar',         'bar'),
    ('drink',       'juice'),

    # ── Meal-time and house names ─────────────────────────────────────────
    ('dinner',      'dinner'),
    ('lunch',       'dinner'),
    ('special',     'special'),
)


def _candidates(name):
    """Whole tokens only — plus the collapsed form, plus singulars.

    Substring matching is what put `rum` inside `Rumali Roti`, so every
    candidate is compared by set membership and never by `in` on a string.
    """
    slug = slugify(name or '')
    tokens = {t for t in slug.split('-') if t}
    out = set(tokens)
    out.add(slug.replace('-', ''))       # `Mo:Mo` -> `momo`
    for t in tokens:
        if t.endswith('es'):
            out.add(t[:-2])              # `potatoes` -> `potato`
        if t.endswith('s'):
            out.add(t[:-1])              # `soups` -> `soup`
    out.discard('')
    return out


def for_section(name):
    """-> the icon key for a printed section name, `dish` when nothing fits."""
    found = _candidates(name)
    for token, icon in RULES:
        if token in found:
            return icon
    return FALLBACK
