"""Which printed tokens name a dish, and which name a protein.

Two different jobs, one vocabulary file, because both are lists of menu words
with no descriptive content:

* `dish_word` answers "does this fragment say what kind of thing this is?" --
  the question layer 0 asks of a section when the item name is a bare modifier
  (`Apple`, `ABC`, `Mixed`) and cannot identify itself.
* `proteins` answers "what animal or non-animal filling does this name commit
  to?" -- the question the matcher's hardest veto asks.

This is NOT `dish_lexicon.py`. An entry there is a DENOTATION a generator may
draw ("momo means a steamed pleated dumpling"). `juice` and `sandwich` have no
denotation worth drawing and must never reach an image prompt; they are here to
tell two dishes apart, nothing else.

Every word below appears in a section name printed by one of the four live
venues -- measured 2026-08-02 across their 70 distinct category names. It is
extended as real menus arrive, never speculatively.
"""
import re
import unicodedata

_TOKENS = re.compile(r'[^a-z0-9]+')

# Nouns that say what KIND of thing a row is. Singular; a trailing plural `s`
# is stripped at lookup when the singular is one of these.
DISH_WORDS = frozenset({
    # drinks
    'juice', 'lassi', 'shake', 'milkshake', 'smoothie', 'coffee', 'tea',
    'mocktail', 'cocktail', 'beer', 'wine', 'whisky', 'whiskey', 'vodka',
    'rum', 'gin', 'brandy', 'hookah', 'shisha',
    # plated
    'momo', 'dumpling', 'thukpa', 'chowmein', 'noodle', 'soup', 'pizza',
    'pasta', 'spaghetti', 'penne', 'sandwich', 'burger', 'wrap', 'salad',
    'pancake', 'toast', 'dessert', 'rice', 'roti', 'chapati', 'thali',
    'khaja', 'sekuwa', 'pakoda', 'snack', 'omelette', 'biryani', 'dal',
    'curry', 'steak', 'fries', 'sizzler', 'bowl', 'muesli', 'porridge',
    'cornflakes', 'potato', 'egg',
})

# Surface form -> the canonical token the veto compares. Two spellings of one
# protein must NOT read as a conflict; two proteins must.
PROTEINS = {
    'veg': 'veg', 'vegetable': 'veg', 'vegetarian': 'veg',
    'vegan': 'vegan',
    'egg': 'egg',
    'chicken': 'chicken', 'chikken': 'chicken',
    'buff': 'buff', 'buffalo': 'buff',
    'pork': 'pork', 'bacon': 'pork', 'ham': 'pork',
    'fish': 'fish', 'tuna': 'fish',
    'prawn': 'prawn', 'shrimp': 'prawn',
    'mutton': 'mutton', 'lamb': 'mutton', 'goat': 'mutton',
    'beef': 'beef',
    'paneer': 'paneer',
    'mushroom': 'mushroom',
}


def _tokens(text):
    """Whole lowercase alphanumeric tokens. `MO:MO` -> ('mo', 'mo')."""
    if not text:
        return ()
    decomposed = unicodedata.normalize('NFKD', str(text))
    plain = ''.join(c for c in decomposed if not unicodedata.combining(c))
    return tuple(t for t in _TOKENS.split(plain.lower()) if t)


# Spellings real cards print for a dish word already in DISH_WORDS. Same shape
# as PROTEINS: surface form -> canonical. Two of these are live category names
# in this platform's own data -- `Deserts` (a typo for Desserts, and a menu
# section spelled that way is never about sand) and `Shisa (Hukka)`. Both were
# invisible to the first version of this module, which mattered because a
# shisha row IS a bare flavour name (`Mint`, `Grape`) and is exactly the case
# section completion exists to disambiguate.
#
# Extended when a real card prints a spelling, never speculatively.
DISH_SYNONYMS = {
    'desert': 'dessert',
    'shisa': 'shisha',
    'hukka': 'hookah',
}


def _singular(token):
    """`desserts` -> `dessert`, `sandwiches` -> `sandwich`.

    Two plural shapes, because the venues print both: `Soups`/`Salads`/
    `Desserts` take a bare `s`, while `Sandwiches` takes `-es` and stripping
    one character leaves `sandwiche`, which is not a word in any vocabulary.

    Mirrors `category_icons._candidates`, which solved this same problem for
    section icons: try the token, then `-es`, then `-s`, and let membership in
    DISH_WORDS decide. Conditional on purpose -- blindly stripping invents
    words (`chips` -> `chip`, `bass` -> `bas`), and a vocabulary that invents
    words is worse than one that misses them.
    """
    candidates = [token]
    if token.endswith('es'):
        candidates.append(token[:-2])
    if token.endswith('s'):
        candidates.append(token[:-1])
    for candidate in candidates:
        if candidate in DISH_WORDS:
            return candidate
        if candidate in DISH_SYNONYMS:
            return DISH_SYNONYMS[candidate]
    return token


def dish_word(text):
    """The first dish noun in `text`, reading left to right, or ''.

    First rather than most-specific: `Milk Shake / Lassi` and `Chowmin /
    Thukpa` each name two dishes and neither is more correct. What matters is
    that the choice is DETERMINISTIC -- the backfill and the matcher both
    derive the key, and a rule that reads differently on two calls matches
    nothing.
    """
    from menu.pipeline import name_norm
    for token in _tokens(name_norm.normalize(text)):
        candidate = _singular(token)
        if candidate in DISH_WORDS:
            return candidate
    return ''


def has_dish_word(text):
    """Does this fragment say what kind of thing it is?"""
    return bool(dish_word(text))


def proteins(text):
    """The canonical protein tokens `text` commits to. May be empty."""
    return frozenset(PROTEINS[t] for t in _tokens(text) if t in PROTEINS)
