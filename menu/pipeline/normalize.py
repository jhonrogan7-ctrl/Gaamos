"""Post-extraction validators for the canonical menu-item model.

The guarantees of the extraction contract live HERE, not in the prompt: prompt
wording drifts between model versions, these functions do not. Every rule in
this module is a unit test that makes no API call.
"""
import re

from menu.dietary import DIETARY_VOCAB

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text):
    """Lowercase alphanumeric words. Case and punctuation are irrelevant when
    asking whether a tag actually came from the printed name."""
    return set(_TOKEN_RE.findall((text or "").lower()))


def _nonempty(values):
    """Stripped, lowercased, de-duplicated, blanks removed."""
    return list(dict.fromkeys(
        (v or "").strip().lower() for v in (values or []) if (v or "").strip()))


def clean_tags(tags, raw_name):
    """Drop any tag containing a word that is not in `raw_name`.

    Founder decision D6: tags come from the printed menu item name only. The AI
    may split that name into words; it may never add a synonym, translation or
    inferred ingredient. Enforced here rather than by prompt wording, so a future
    model version cannot quietly start inventing.
    """
    allowed = _tokens(raw_name)
    out = []
    for tag in _nonempty(tags):
        words = _tokens(tag)
        if words and words <= allowed and tag not in out:
            out.append(tag)
    return out


def clean_dietary(values):
    """Drop anything outside DIETARY_VOCAB (D7)."""
    return [v for v in _nonempty(values) if v in DIETARY_VOCAB]


def clean_price(value):
    """A non-negative int, or None. Never coerced from a string."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value >= 0 and value.is_integer() else None
    return None


def clean_currency(value):
    """A three-letter uppercase code; anything else falls back to NPR."""
    cleaned = (value or "").strip().upper()
    return cleaned if len(cleaned) == 3 and cleaned.isalpha() else "NPR"
