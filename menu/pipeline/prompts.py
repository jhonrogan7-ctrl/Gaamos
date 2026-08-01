"""Compose the image prompt for one menu item.

Lifted out of `prompt_sheet` so the platform wizard can compose a prompt for a
row that was photographed rather than transcribed. The composition itself is
unchanged and must stay unchanged: `menu/tests/fixtures/prompt_golden.json` pins
every prompt the four live venues' sheets produce, byte for byte.

A style block describes CAMERA AND LIGHT ONLY. It must never describe the food
or the drink -- that is the item's job, and the printed name is the only thing
that licenses a claim. Two phrases here once did: `fresh vibrant colours,
appetising` put invented garnish on every pale dish, and `condensation on the
glass` served all 11 Chill Zone hot drinks cold.
"""
from django.utils.text import slugify

from menu.pipeline import dish_lexicon

FOOD_STYLE = (", professional food photography, 45-degree angle, natural "
              "window light, shallow depth of field, dark rustic wood table, "
              "high detail, the dish only, no garnish, no herbs, no sauce, "
              "no side dishes, no props")
DRINK_STYLE = (", professional beverage photography, straight-on angle, soft "
               "natural light, clean neutral background, high detail, "
               "the drink only, no garnish, no props")

# Section-name keywords that make a section a drink section. Matched on the
# section, never the item: "Can Juice" sits in Soft Drinks, and "Hard Drinks"
# must land on the drink block too.
_DRINK_WORDS = ('drink', 'juice', 'lassi', 'shake', 'beer', 'cocktail', 'wine',
                'whisky', 'whiskey', 'vodka', 'brandy')

# Spirits whose name is a substring of a food's: `rum` sits inside `Rumali
# Roti` and `gin` inside `Ginger Chicken`. A bar card names these as the whole
# section, so they are matched on the section slug exactly.
_DRINK_SECTIONS = frozenset({'rum', 'gin'})


def is_drink(section):
    low = (section or '').lower()
    return slugify(section or '') in _DRINK_SECTIONS \
        or any(w in low for w in _DRINK_WORDS)


def compose(subject, *, name, drink):
    """Subject line, expanded through the dish lexicon, then the style block.

    The lexicon goes in the middle deliberately: the style block must stay last
    so its negative clauses ("no garnish", "no props") are the final thing the
    model reads.
    """
    expanded = dish_lexicon.expand(subject, name, drink=drink)
    return expanded + (DRINK_STYLE if drink else FOOD_STYLE)


def for_item(name, section, subject=''):
    """A prompt for an item with no sheet behind it.

    With no transcribed subject the printed name IS the subject -- the lexicon
    may say what a word already denotes, and nothing may add to it.
    """
    drink = is_drink(section)
    return compose(subject or name, name=name, drink=drink)
