"""NVIDIA vision adapter: a menu document to structured JSON.

Reuses `extract.py`'s prompt and item schema VERBATIM. Those transcription rules
-- never invent an item that is not printed, one item per price in a
`HALF | FULL` matrix, tags only from words in the printed name, a low confidence
rather than a guess on a misaligned price column -- are hard-won and
provider-independent. Only the transport changes.

Five behaviours here are measured requirements, not preferences (probe of
2026-07-30, `nvidia/nemotron-nano-12b-v2-vl` on a two-column card with 36 items
in 5 shared-line price matrices):

1. Guided JSON is MANDATORY. Same model, same prompt, same image: 36/36 items
   with it, 26/36 without -- and the ten it drops are exactly the protein
   variants. A dropped Buff Momo is a lost item; a merged one carries veg,
   chicken and buff into one row's dietary_tags, which is the protein-veto
   nightmare arriving before the matcher can see it. It is requested through
   `nv.guided_json` (`response_format`), NOT `nvext`: this host accepts `nvext`
   and ignores it, and an unguided call to this model loops to max_tokens.
2. Guide on the ITEM ARRAY only. Including the `pages` wrapper is what sent the
   8B model into a 230-entry repetition loop. Page type is inferred from the
   item count here instead.
3. Tolerate a bare array, an object wrapper, and a spurious null-price parent
   row (the guided run emitted `Thukpa soup (noodles) :` beside its three
   correct variants).
4. Force `currency = NPR`. The unguided run volunteered `INR`.
5. Compose the display name in code. The model leaves `name` as the shared
   printed line on every variant and puts the difference only in
   `variant_label`.

Two more came from the 2026-08-02 live run, in which 27 of 159 prices on a real
card were invented -- 25 where a spread's price column was cut off at the
binding, 2 where the cell was simply blank:

6. VERIFY EVERY PRICE against a second, independent look at the page --
   available, but OFF unless `MENU_PRICE_VERIFY` or `verify=True` says
   otherwise. The model does not know it is guessing and cannot be asked:
   `confidence` was 1 on all 27, `raw_price_text` was confabulated to match the
   invented number, and a guided `price_source` enum is not available at all
   (adding one to the item schema returns HTTP 500). An unverifiable price
   becomes None and the row is flagged `price_unverified` -- never a guess, per
   the founder rule of 2026-07-24. The name is kept; it is the price that is
   unknown.

   ⚠ WHY IT SHIPS OFF (founder call, 2026-08-02). It has only ever run against a
   stub verifier, so the number that decides whether it is a net win -- how many
   TRUE printed prices it nulls as collateral on a real card -- does not exist.
   An over-eager guard nulls a correct menu, which is its own kind of wrong. 25
   of the 27 fabrications came from one spread photographed at an angle with its
   price column cut off at the binding, and an upload-quality rule at gate 1
   addresses those without a second inference pass. The remaining 2 came from a
   BLANK PRICE CELL on a perfectly legible page, and no upload rule reaches
   them, which is why this code stays. Measure the collateral, then decide.
7. Drop what is not a menu item. A QR-code caption arrives priced at zero, and a
   cover page arrives as a few unpriced words. This is ALWAYS on -- it needs no
   extra request and nothing it removes was ever a menu row. Ordering matters:
   it runs BEFORE verification, which deliberately nulls prices.

⚠ CONSEQUENCE OF SHIPPING WITH RULE 6 OFF: this adapter never emits a null price
for a menu item. Gate 1's blocking rule -- "a row with no price cannot advance
unless explicitly marked deliberately unpriced" -- will therefore never fire on
its own. The split-screen human check is the only thing catching a blank-cell
item. Do not build gate 1 assuming nulls arrive.

One request per page (~110 s); with verification on it is two (~110 s + ~34 s)
and a page costs two slots of the 6/min vision budget, which is why phase 4 runs
documents as parallel jobs.
"""
import base64
import json
import re
import urllib.request
from collections import Counter

from menu.pipeline import nv, rasterize, throttle
from menu.pipeline.extract import _ITEM_SCHEMA, _PROMPT

# Rule 2: the array, and nothing wrapping it.
_GUIDED_SCHEMA = {'type': 'array', 'items': _ITEM_SCHEMA}

# Rule 6. Deliberately narrow: it asks for one thing and offers no room to
# describe an item, because the moment it can name a dish it starts pricing one.
_VERIFY_PROMPT = (
    'Transcribe ONLY the prices printed in this image, in reading order '
    '(left column fully, then right column). Output one entry per printed '
    'price, with the section heading it sits under and the exact printed '
    'digits. Do not list an item that has no printed price. Do not infer or '
    'estimate a price. If a price is cut off, hidden or unreadable, leave it '
    'out entirely.')

_VERIFY_SCHEMA = {'type': 'array', 'items': {
    'type': 'object',
    'properties': {'section': {'type': 'string'},
                   'printed_price': {'type': 'string'}},
    'required': ['printed_price']}}


def _model():
    from django.conf import settings
    return settings.NVIDIA_VISION_MODEL


def _verify_enabled():
    from django.conf import settings
    return settings.MENU_PRICE_VERIFY


def _rows_from(text):
    """The item list out of whatever shape came back (rule 3)."""
    try:
        payload = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f'vision model did not return JSON: {str(text)[:200]!r}') from exc
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for field in ('items', 'data', 'results'):
            if isinstance(payload.get(field), list):
                return payload[field]
    raise ValueError(f'vision model did not return JSON items: {str(text)[:200]!r}')


def _display_name(row):
    """Rule 5 -- built here, never requested from the model."""
    base = (row.get('base_name') or '').strip()
    variant = (row.get('variant_label') or '').strip()
    if base and variant:
        return f'{base} ({variant})'
    return (row.get('name') or base or row.get('raw_name') or '').strip()


def _is_parent_row(row, rows):
    """A null-price row whose variants carry the prices (rule 3).

    Distinguished from a genuinely unpriced item -- 'Soup of the Day' with no
    number beside it -- by whether any OTHER row shares its base name and does
    have a price. A real unpriced row survives, because gate 1 exists to ask a
    human about exactly those.
    """
    if row.get('price') is not None:
        return False
    base = (row.get('base_name') or row.get('name') or '').strip().rstrip(':').strip()
    if not base:
        return False
    return any(other is not row
               and other.get('price') is not None
               and (other.get('base_name') or '').strip() == base
               for other in rows)


def _clean(rows, page_number):
    out = []
    for row in rows:
        if not isinstance(row, dict) or _is_parent_row(row, rows):
            continue
        row = dict(row)
        row['name'] = _display_name(row)
        row['currency'] = 'NPR'                      # rule 4
        row['source_page'] = page_number
        if not row['name']:
            continue
        row.setdefault('raw_name', row['name'])
        out.append(row)
    return out


def _printed_digits(value):
    """The integer a transcribed price denotes, or None if it holds no digits.

    Measured: asked for printed prices the model returns bare digits, but also
    'Rs. 250', and -- for the two rows whose price cell is blank -- the item
    name where the digits would go. A name yields None and claims nothing.
    """
    digits = re.sub(r'[^0-9]', '', str(value if value is not None else ''))
    return int(digits) if digits else None


def _observed_prices(page, *, model, key, opener, throttled):
    """A second, independent look at the page: what prices are actually printed?

    A separate request on purpose. Asking the same call to mark its own
    uncertainty does not work -- `confidence` came back 1 on all 27 fabricated
    prices and `raw_price_text` was confabulated to match them -- and asking via
    a guided enum is not even available: adding one to the item schema makes the
    endpoint return HTTP 500.
    """
    if throttled:
        throttle.acquire(model)
    body = {
        'model': model,
        'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': _VERIFY_PROMPT},
            {'type': 'image_url', 'image_url': {'url':
                'data:image/jpeg;base64,' + base64.b64encode(page).decode()}},
        ]}],
        'max_tokens': 4096,
        'temperature': 0.0,
        **nv.guided_json(_VERIFY_SCHEMA, name='prices'),
    }
    reply = nv.post('/chat/completions', body, key=key, opener=opener)
    counts = Counter()
    for row in _rows_from(nv.message_text(reply)):
        if isinstance(row, dict):
            value = _printed_digits(row.get('printed_price'))
            if value is not None:
                counts[value] += 1
    return counts


def _has_price_evidence(row):
    price = row.get('price')
    return bool((price is not None and price != 0)
                or (row.get('raw_price_text') or '').strip())


def _drop_junk(rows):
    """Rows that are not menu items at all (rule 7).

    Two shapes, both measured. A QR-code caption comes back priced at ZERO with
    no printed price text -- 'Global IME Bank', 'E-Sewa' -- and zero is never a
    menu price. A cover page comes back as a handful of unpriced words; a page
    on which NOTHING carries a price is not a menu page, so its rows go together.

    Deliberately page-level for the second case: an unpriced item sitting beside
    priced ones is a real row ('Soup of the Day'), and gate 1 exists to ask a
    human about exactly those.
    """
    kept = [row for row in rows if row.get('price') != 0 or _has_price_evidence(row)]
    if not any(_has_price_evidence(row) for row in kept):
        return []
    return kept


def _verify(rows, observed):
    """Spend an observed price per item; null and flag whatever cannot pay.

    Consumption, not mere matching: the occluded half of a spread invents a
    ladder of round numbers that the legible half really does print, so one
    printed 250 must not validate five items claiming 250.
    """
    for row in rows:
        price = row.get('price')
        if price is None:
            continue
        if observed[price] > 0:
            observed[price] -= 1
        else:
            row['price'] = None
            row['price_unverified'] = True
    return rows


def extract_menu(file_bytes, mime, *, model=None, api_key=None,
                 opener=urllib.request.urlopen, throttled=True, verify=None):
    """-> {"pages": [...], "items": [...]} — the same contract `extract.extract_menu` returns."""
    model = model or _model()
    verify = _verify_enabled() if verify is None else verify
    key = nv.api_key() if api_key is None else api_key
    if not key:
        raise ValueError(
            'No NVIDIA API key: pass api_key= or set NVIDIA_API_KEY in .env')

    items, pages = [], []
    for number, page in enumerate(rasterize.pages_of(file_bytes, mime), start=1):
        if throttled:
            throttle.acquire(model)
        data_url = 'data:image/jpeg;base64,' + base64.b64encode(page).decode()
        body = {
            'model': model,
            'messages': [{'role': 'user', 'content': [
                {'type': 'text', 'text': _PROMPT},
                {'type': 'image_url', 'image_url': {'url': data_url}},
            ]}],
            'max_tokens': 8192,
            'temperature': 0.0,
            # Rules 1 + 2. Via `response_format`, never `nvext` -- see
            # `nv.guided_json` for the measurement that forced that.
            **nv.guided_json(_GUIDED_SCHEMA, name='menu_items'),
        }
        reply = nv.post('/chat/completions', body, key=key, opener=opener)
        rows = _clean(_rows_from(nv.message_text(reply)), number)
        # Junk BEFORE verification: verification deliberately nulls prices, so
        # a junk filter running after it would delete the rows it just guarded.
        rows = _drop_junk(rows)
        if rows and verify:
            rows = _verify(rows, _observed_prices(
                page, model=model, key=key, opener=opener, throttled=throttled))
        items.extend(rows)
        # Rule 2: page type from the item count, not from the model.
        pages.append({'index': number,
                      'page_type': 'menu' if rows else 'unknown',
                      'confidence': 1.0 if rows else 0.0})
    return {'pages': pages, 'items': items}
