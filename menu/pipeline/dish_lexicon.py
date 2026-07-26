"""What a menu word already denotes, in the form a generator can draw.

The printed cards this pipeline reads carry names and prices only — no
descriptions — so the item name has to carry the whole load. A generator that
does not know `momo` draws meatballs, and one that does not know `masala` draws
red sauce; both happened on the Chill Zone run.

An entry here is a DENOTATION, not an addition. `momo` means a steamed pleated
dumpling; saying so adds no claim the printed name did not already make. A word
whose plating the name does not determine does not belong in this file — it
belongs in a `*skip — ask the venue*` row on the sheet.

Nothing here may assert a quantity. Counts come from the printed card.
"""
from django.utils.text import slugify

# Dish head-words. Applied in every section.
LEXICON = {
    'momo':      'steamed pleated dumplings',
    'jhol':      'in a thin spiced soup',
    'thali':     'a round steel tray of rice with small bowls of curry and dal',
    'khaja':     'a steel plate of beaten rice with small side portions',
    'pakoda':    'battered fritters',
    'sadeko':    'a cold tossed spiced salad-style dish',
    'chowmein':  'stir-fried noodles',
    'thukpa':    'noodles in a clear broth',
    'masala':    'speckled with chopped onion, chilli and coriander',
    'omelette':  'a folded flat cooked-egg omelette',
    'paneer':    'cubes of white paneer cheese',
    'palak':     'in a green spinach gravy',
    'dal':       'yellow lentil soup',
    'biryani':   'spiced long-grain rice',
    'roti':      'a flat round unleavened flatbread',
    'chapati':   'a flat round unleavened flatbread',
    'lassi':     'a thick yoghurt drink in a tall glass',
    'sizzler':   'served on a cast-iron platter',
    'tandoori':  'clay-oven charred',
    'sekuwa':    'skewer-grilled marinated meat',
    'chatamari': 'a thin round rice-flour crepe',
    'dhido':     'a stiff dark buckwheat porridge mound',
    'gundruk':   'dark fermented leafy greens',
    'timur':     'speckled with Sichuan-pepper',
}

# Serving and temperature. Applied in DRINK sections only: `Hot & Sour Soup`
# and `Hot Chocolate` share the token `hot`, and only one is about temperature.
DRINK_LEXICON = {
    'hot':  'served hot, steam rising',
    'ice':  'served over ice in a tall glass',
    'iced': 'served over ice in a tall glass',
    'cold': 'served over ice in a tall glass',
}


# Head-words whose denotation describes a PLATED DISH, so it must not be
# asserted of a beverage: `masala` on a plate is chopped onion, chilli and
# coriander, and applied to Masala Tea that puts onion in the glass. The card
# does not print which spices the chai holds, so nothing replaces it — the row
# keeps its bare subject. Not a blanket exclusion: `lassi` also lives in
# LEXICON and already denotes a drink, so a drink section keeps it.
_FOOD_ONLY = frozenset({'masala'})


def _vocabulary(drink):
    if not drink:
        return LEXICON
    return {**{w: d for w, d in LEXICON.items() if w not in _FOOD_ONLY},
            **DRINK_LEXICON}


def head_words(name, *, drink=False):
    """Lexicon words present in `name`, as whole slug tokens.

    Token matching, not substring: `Pomodoro` must not read as `momo`.
    """
    tokens = set(slugify(name).split('-'))
    return [w for w in _vocabulary(drink) if w in tokens]


def expand(prompt, name, *, drink=False):
    """`prompt` plus the denotation of every head-word it does not already state.

    Two head-words can share one denotation -- `roti` and `chapati` both mean
    "a flat round unleavened flatbread". Checked against what has already been
    queued, not just the original prompt, so the phrase is not appended twice.
    """
    vocabulary = _vocabulary(drink)
    low = prompt.lower()
    extra, seen = [], set()
    for w in head_words(name, drink=drink):
        denotation = vocabulary[w]
        if denotation.lower() in low or denotation in seen:
            continue
        extra.append(denotation)
        seen.add(denotation)
    return prompt + (', ' + ', '.join(extra) if extra else '')


def needs_definition(row):
    """A row the generator has no way to get right: it will be drawn, its name
    contains no word we can define, and the card printed no description.

    Reported rather than guessed at — these become a lexicon entry with founder
    sign-off, or a `*skip — ask the venue*` row.
    """
    return bool(row['generatable']) and not row['description'] \
        and not head_words(row['item'], drink=row['drink'])
