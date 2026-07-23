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


def page_type_map(payload):
    """{page index: page_type} from the extraction manifest."""
    return {p.get("index"): (p.get("page_type") or "menu")
            for p in (payload.get("pages") or [])}


def normalize_item(raw, page_types=None, *, threshold=None):
    """Map one raw extracted item onto the canonical field set.

    Returns a dict whose keys are exactly the Item fields the extraction task
    assigns, plus `needs_review`. `page_types` comes from page_type_map, so an
    item lifted off a signboard or a screenshot of someone else's menu is
    flagged rather than trusted.
    """
    if threshold is None:
        from django.conf import settings
        threshold = settings.SCAN_CONFIDENCE_THRESHOLD
    page_types = page_types or {}

    raw_name = (raw.get("raw_name") or raw.get("name") or "").strip()
    tags_in, dietary_in = raw.get("tags"), raw.get("dietary_tags")
    tags = clean_tags(tags_in, raw_name)
    dietary = clean_dietary(dietary_in)
    price = clean_price(raw.get("price"))
    currency = clean_currency(raw.get("currency"))
    source_page = raw.get("source_page")
    page_type = page_types.get(source_page, "menu")

    try:
        confidence = float(raw.get("confidence", 1.0))
    except (TypeError, ValueError):
        confidence = 0.0

    # A dropped value means the model tried to add something of its own.
    dropped = (len(tags) < len(_nonempty(tags_in))
               or len(dietary) < len(_nonempty(dietary_in)))

    return {
        "name": (raw.get("name") or raw_name).strip(),
        "base_name": (raw.get("base_name") or "").strip(),
        "variant_label": (raw.get("variant_label") or "").strip(),
        "description": (raw.get("description") or "").strip(),
        "category": (raw.get("category") or "").strip(),
        "tags": tags,
        "dietary_tags": dietary,
        "reference_price": price,
        "currency": currency,
        "raw_name": raw_name,
        "raw_price_text": (raw.get("raw_price_text") or "").strip(),
        "raw_section": (raw.get("raw_section") or "").strip(),
        "split_from": (raw.get("split_from") or "").strip(),
        "source_page": source_page,
        "confidence": confidence,
        "needs_review": bool(
            confidence < threshold
            or price is None
            or page_type != "menu"
            or currency != "NPR"
            or dropped),
    }
