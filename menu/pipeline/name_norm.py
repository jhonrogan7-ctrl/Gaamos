"""Normalize a printed menu name into the key the library and matcher compare on.

Four venues print one dish four ways -- `Chow Mein`, `Chowmein`, `CHOW-MIN`,
`Chowmin (Veg.)` -- and a matcher that compares printed strings finds none of
them. This module is the single place that decides what "the same printed name"
means. Every rule is data-driven and tested, because a wrong fold here does not
fail loudly: it silently mismatches every menu that follows.

It decides nothing about whether two dishes ARE the same dish -- that is the
matcher's job, protein veto included. This only produces the key it compares on.
"""
import re
import unicodedata

_NON_ALNUM = re.compile(r'[^a-z0-9]+')
_WS = re.compile(r'\s+')

# Orthographic variants real Nepali cards print for one dish. Applied to the
# already-lowercased, punctuation-stripped form, so `Mo:Mo` arrives as `mo mo`.
#
# Every pattern is anchored on word boundaries. The governing bug in this
# codebase is substring matching -- `rum` inside `Rumali Roti`, `momo` inside
# `Pomodoro` -- and it has reached production twice.
_FOLDS = (
    (re.compile(r'\bchow\s*mein\b|\bchow\s*min\b|\bchowmian\b|\bchaumin\b'), 'chowmein'),
    (re.compile(r'\bmo\s+mo\b|\bmomos\b'), 'momo'),
    (re.compile(r'\bpakauda\b|\bpakora\b'), 'pakoda'),
)

# A measure the card prints beside a name rather than as part of it.
_UNIT = r'\d+(?:\.\d+)?\s*(?:ml|cl|ltr|l|g|gm|kg|pc|pcs|piece|pieces)'
# Pulled off a BARE name: unambiguous, never part of a dish's name.
_MEASURE = re.compile(rf'^(?:{_UNIT}|half|full|qtr|quarter)$')
# Pulled off a SEPARATED name (`Black Tea / Hot`): the card's own punctuation
# says this is a serving, so the wider vocabulary is safe here and only here.
_SERVING = re.compile(rf'^(?:{_UNIT}|half|full|qtr|quarter|small|medium|large'
                      r'|regular|hot|ice|iced|cold)$')

# `Thukpa Soup (Egg)`, `Ruslan Vodka (Qtr.)`, `8848 (180 ml)`. Whatever it says
# is the variant: guessing which parentheticals are "really" variants is how a
# Veg row and a Buff row end up sharing one key.
_PAREN = re.compile(r'\s*\(([^()]*)\)\s*$')
_SEPARATED = re.compile(r'^(.*?)\s*[-–—/,]\s*([^-–—/,]+)$')


def normalize(text):
    """The comparable form of any printed fragment.

    Lowercased, unaccented, `&` spelled out, punctuation dropped, orthographic
    variants folded, whitespace collapsed.
    """
    if not text:
        return ''
    decomposed = unicodedata.normalize('NFKD', str(text))
    plain = ''.join(c for c in decomposed if not unicodedata.combining(c))
    lowered = plain.lower().replace('&', ' and ')
    folded = _WS.sub(' ', _NON_ALNUM.sub(' ', lowered)).strip()
    for pattern, canonical in _FOLDS:
        folded = pattern.sub(canonical, folded)
    return _WS.sub(' ', folded).strip()


def split_variant(name):
    """`printed name` -> (base, variant), both exactly as printed.

    Three shapes, in this order: a trailing parenthetical, a separated trailing
    serving word, a bare trailing measure. A name with no variant returns
    `(name, '')`.
    """
    text = (name or '').strip()
    match = _PAREN.search(text)
    if match:
        return _PAREN.sub('', text).strip(), match.group(1).strip()
    match = _SEPARATED.match(text)
    if match and _SERVING.match(normalize(match.group(2))):
        return match.group(1).strip(), match.group(2).strip()
    parts = text.rsplit(' ', 1)
    if len(parts) == 2 and _MEASURE.match(normalize(parts[1])):
        return parts[0].strip(), parts[1].strip()
    return text, ''


def search_form(name):
    """The value stored in `Item.search_name`: the normalized base name."""
    return normalize(split_variant(name)[0])


def entry_key(name):
    """(search_name, normalized variant) -- the library's identity for a name."""
    base, variant = split_variant(name)
    return normalize(base), normalize(variant)
