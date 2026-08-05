"""The vision adapter, and the four tolerances the live probe forced on it.

Every assertion below traces to a measured behaviour of
`nvidia/nemotron-nano-12b-v2-vl` on 2026-07-30, not to a guess about what a
model might do.
"""
import io
import json
from unittest.mock import patch

import pytest
from PIL import Image

from menu.pipeline import extract, extract_nv


def _png(w=800, h=600):
    buf = io.BytesIO()
    Image.new('RGB', (w, h), (240, 240, 240)).save(buf, format='PNG')
    return buf.getvalue()


captured = {}


def _opener(payload, observed=None):
    """Stand in for the endpoint; record what the adapter sent.

    A page is one call by default and TWO when `verify=True` -- the extraction,
    then the independent price-verification pass. This dispatches on which one
    is being made, and `captured` always holds the EXTRACTION body, which is
    what the request-shape tests assert on.

    Unless a test passes `observed`, the verifier is told it saw exactly the
    prices the extraction returned, so items survive reconciliation untouched
    and a test about naming or currency stays a test about naming or currency.
    """
    def opener(req, timeout=None):
        body = json.loads(req.data.decode())
        name = (body.get('response_format', {})
                    .get('json_schema', {}).get('name'))
        if name == 'prices':
            seen = observed
            if seen is None:
                rows = json.loads(payload['choices'][0]['message']['content'])
                rows = rows if isinstance(rows, list) else rows.get('items', [])
                seen = [r['price'] for r in rows
                        if isinstance(r, dict) and r.get('price') is not None]
            return io.BytesIO(json.dumps(_chat(
                [{'printed_price': str(p)} for p in seen])).encode())
        captured['url'] = req.full_url
        captured['headers'] = {k.lower(): v for k, v in req.headers.items()}
        captured['body'] = body
        return io.BytesIO(json.dumps(payload).encode())
    return opener


def _chat(content):
    return {'choices': [{'message': {'content': json.dumps(content)}}]}


ONE_ITEM = [{'name': 'Black Tea', 'raw_name': 'Black Tea', 'price': 50,
             'source_page': 1}]


def test_the_prompt_is_the_gemini_prompt_verbatim():
    """Those transcription rules are hard-won and provider-independent -- 'never
    invent an item that is not printed', one item per price in a matrix, tags
    only from the printed name. Only the transport changes."""
    assert extract_nv._PROMPT is extract._PROMPT


def test_the_request_carries_guided_json_because_without_it_ten_items_vanish():
    """36/36 items with guided decoding, 26/36 without -- and the ten it drops
    are exactly the protein variants inside the price matrices.

    Sent as `response_format`, never `nvext`: measured 2026-08-02, this host
    accepts `nvext.guided_json` and ignores it, returning a reply
    byte-identical to an unguided one."""
    extract_nv.extract_menu(_png(), 'image/png', model='m', api_key='k',
                            opener=_opener(_chat(ONE_ITEM)), throttled=False)
    assert captured['body']['response_format']['type'] == 'json_schema'
    assert 'nvext' not in captured['body']


def test_the_guided_schema_is_the_item_array_only():
    """Guiding on the `pages` wrapper is what sent the 8B model into a 230-entry
    repetition loop. Page type is decided from the item count instead."""
    extract_nv.extract_menu(_png(), 'image/png', model='m', api_key='k',
                            opener=_opener(_chat(ONE_ITEM)), throttled=False)
    schema = captured['body']['response_format']['json_schema']['schema']
    assert schema['type'] == 'array'
    assert 'pages' not in json.dumps(schema)


def test_the_key_travels_in_the_authorization_header():
    extract_nv.extract_menu(_png(), 'image/png', model='m', api_key='k',
                            opener=_opener(_chat(ONE_ITEM)), throttled=False)
    assert captured['headers']['authorization'] == 'Bearer k'


def test_the_page_is_sent_as_an_inline_data_url():
    extract_nv.extract_menu(_png(), 'image/png', model='m', api_key='k',
                            opener=_opener(_chat(ONE_ITEM)), throttled=False)
    parts = captured['body']['messages'][0]['content']
    urls = [p['image_url']['url'] for p in parts if p['type'] == 'image_url']
    assert len(urls) == 1
    assert urls[0].startswith('data:image/jpeg;base64,')


def test_a_bare_array_response_is_accepted():
    """The 12B returns a bare array regardless of what the schema wraps."""
    out = extract_nv.extract_menu(_png(), 'image/png', model='m', api_key='k',
                                  opener=_opener(_chat(ONE_ITEM)), throttled=False)
    assert [i['name'] for i in out['items']] == ['Black Tea']


def test_an_object_wrapped_response_is_also_accepted():
    out = extract_nv.extract_menu(
        _png(), 'image/png', model='m', api_key='k',
        opener=_opener(_chat({'items': ONE_ITEM})), throttled=False)
    assert [i['name'] for i in out['items']] == ['Black Tea']


def test_a_spurious_null_price_parent_row_is_dropped_not_crashed_on():
    """Measured: the guided run emitted `Thukpa soup (noodles) :` with a null
    price beside its three correct variants."""
    rows = [{'name': 'Thukpa soup (noodles) :', 'raw_name': 'Thukpa soup (noodles) :',
             'price': None, 'source_page': 1, 'base_name': 'Thukpa soup'},
            {'name': 'x', 'raw_name': 'Thukpa soup', 'base_name': 'Thukpa soup',
             'variant_label': 'Veg', 'price': 165, 'source_page': 1},
            {'name': 'x', 'raw_name': 'Thukpa soup', 'base_name': 'Thukpa soup',
             'variant_label': 'Egg', 'price': 195, 'source_page': 1}]
    out = extract_nv.extract_menu(_png(), 'image/png', model='m', api_key='k',
                                  opener=_opener(_chat(rows)), throttled=False)
    assert len(out['items']) == 2
    assert all(i['price'] for i in out['items'])


def test_a_genuinely_unpriced_item_survives():
    """Only a parent row -- one whose variants carry the prices -- is dropped. An
    unpriced item is a real row that gate 1 asks a human about.

    It sits beside a priced item because that is where it occurs on a real card:
    a page on which NOTHING carries a price is not a menu page, and is handled by
    test_a_page_with_no_printed_price_anywhere_is_not_a_menu_page."""
    rows = [{'name': 'Soup of the Day', 'raw_name': 'Soup of the Day',
             'price': None, 'source_page': 1},
            {'name': 'Black Tea', 'raw_name': 'Black Tea', 'price': 50,
             'raw_price_text': '50', 'source_page': 1}]
    out = extract_nv.extract_menu(_png(), 'image/png', model='m', api_key='k',
                                  opener=_opener(_chat(rows)), throttled=False)
    assert sorted(i['name'] for i in out['items']) == ['Black Tea',
                                                       'Soup of the Day']


# --- The price guard -------------------------------------------------------
# Live run 2026-08-02: 27 of 159 prices were invented -- 25 where a spread's
# price column was cut off at the binding, and 2 where the cell was simply
# blank (Red Bull Yellow/Blue came back at 100). `confidence` was 1 on every
# one of them and `raw_price_text` was confabulated to match, so the guard
# cannot ask the model how sure it is. It asks a second time, narrowly.

def test_a_price_the_verifier_did_not_see_is_nulled_and_flagged():
    """The Red Bull case: the cell is blank on the card and the model invented
    100. Nothing in its own output says so, so an independent pass decides."""
    rows = [{'name': 'Red Bull Yellow', 'raw_name': 'Red Bull Yellow',
             'price': 100, 'raw_price_text': '100', 'source_page': 1}]
    out = extract_nv.extract_menu(_png(), 'image/png', model='m', api_key='k',
                                  opener=_opener(_chat(rows), observed=[]),
                                  throttled=False, verify=True)
    assert out['items'][0]['price'] is None
    assert out['items'][0]['price_unverified'] is True


def test_a_price_the_verifier_did_see_is_kept_and_not_flagged():
    rows = [{'name': 'Black Tea', 'raw_name': 'Black Tea', 'price': 50,
             'raw_price_text': '50', 'source_page': 1}]
    out = extract_nv.extract_menu(_png(), 'image/png', model='m', api_key='k',
                                  opener=_opener(_chat(rows), observed=['50']),
                                  throttled=False, verify=True)
    assert out['items'][0]['price'] == 50
    assert 'price_unverified' not in out['items'][0]


def test_two_items_cannot_both_claim_one_printed_price():
    """Consumption is the point. The occluded half of a spread invented a ladder
    of round numbers that the legible half really does print, so a verified
    price must be spent, not merely matched."""
    rows = [{'name': 'A', 'raw_name': 'A', 'price': 250, 'raw_price_text': '250',
             'source_page': 1},
            {'name': 'B', 'raw_name': 'B', 'price': 250, 'raw_price_text': '250',
             'source_page': 1}]
    out = extract_nv.extract_menu(_png(), 'image/png', model='m', api_key='k',
                                  opener=_opener(_chat(rows), observed=['250']),
                                  throttled=False, verify=True)
    prices = [i['price'] for i in out['items']]
    assert prices.count(250) == 1
    assert prices.count(None) == 1


def test_the_verifier_reads_digits_out_of_whatever_it_transcribed():
    """Measured: asked for printed prices, it returned 'Rs. 250' and, for the
    two items with a blank cell, the item name where the digits would go."""
    rows = [{'name': 'Black Tea', 'raw_name': 'Black Tea', 'price': 250,
             'raw_price_text': '250', 'source_page': 1}]
    out = extract_nv.extract_menu(
        _png(), 'image/png', model='m', api_key='k',
        opener=_opener(_chat(rows), observed=['Rs. 250', 'Red Bull Yellow']),
        throttled=False, verify=True)
    assert out['items'][0]['price'] == 250


def test_a_qr_caption_priced_at_zero_is_dropped_as_junk():
    """Page 2's footer yielded 'WiFi: Kailash cafe', 'Global IME Bank' and
    'E-Sewa' at price 0 with no printed price text. Zero is never a menu price."""
    rows = [{'name': 'Global IME Bank', 'raw_name': 'Global IME Bank',
             'price': 0, 'raw_price_text': '', 'source_page': 1},
            {'name': 'Black Tea', 'raw_name': 'Black Tea', 'price': 50,
             'raw_price_text': '50', 'source_page': 1}]
    out = extract_nv.extract_menu(_png(), 'image/png', model='m', api_key='k',
                                  opener=_opener(_chat(rows)), throttled=False)
    assert [i['name'] for i in out['items']] == ['Black Tea']


def test_a_page_with_no_printed_price_anywhere_is_not_a_menu_page():
    """Page 5 is a chalkboard cover. It yielded 'Kailash Parbat Cafe', 'Food',
    'Music', 'Drinks', 'Jamming Place' -- none with a price or any printed price
    text -- and was then classified `menu` with confidence 1.0."""
    rows = [{'name': n, 'raw_name': n, 'source_page': 1}
            for n in ('Kailash Parbat Cafe', 'Food', 'Music', 'Drinks')]
    out = extract_nv.extract_menu(_png(), 'image/png', model='m', api_key='k',
                                  opener=_opener(_chat(rows)), throttled=False)
    assert out['items'] == []
    assert out['pages'][0]['page_type'] == 'unknown'


def test_the_junk_filter_runs_before_verification_not_after():
    """Ordering is load-bearing: verification deliberately nulls prices, so a
    junk filter running afterwards would delete exactly the rows the guard just
    protected."""
    rows = [{'name': 'Mixed Chowmein', 'raw_name': 'Mixed Chowmein',
             'price': 400, 'raw_price_text': '400', 'source_page': 1}]
    out = extract_nv.extract_menu(_png(), 'image/png', model='m', api_key='k',
                                  opener=_opener(_chat(rows), observed=[]),
                                  throttled=False, verify=True)
    assert len(out['items']) == 1
    assert out['items'][0]['price'] is None


def test_a_page_whose_prices_are_all_unverified_still_returns_its_items():
    """The occluded half of page 3 is 25 real dishes. Their names are worth
    keeping; only their prices are unknown."""
    rows = [{'name': n, 'raw_name': n, 'price': 200, 'raw_price_text': '200',
             'source_page': 1} for n in ('Veg. Chowmein', 'Egg Chowmein')]
    out = extract_nv.extract_menu(_png(), 'image/png', model='m', api_key='k',
                                  opener=_opener(_chat(rows), observed=[]),
                                  throttled=False, verify=True)
    assert len(out['items']) == 2
    assert all(i['price'] is None for i in out['items'])
    assert out['pages'][0]['page_type'] == 'menu'


def test_the_verification_call_asks_only_for_prices_and_guides_the_answer():
    verifying = {}

    def opener(req, timeout=None):
        body = json.loads(req.data.decode())
        name = (body.get('response_format', {})
                    .get('json_schema', {}).get('name'))
        if name == 'prices':
            verifying['body'] = body
            return io.BytesIO(json.dumps(_chat([{'printed_price': '50'}])).encode())
        return io.BytesIO(json.dumps(_chat(ONE_ITEM)).encode())

    extract_nv.extract_menu(_png(), 'image/png', model='m', api_key='k',
                            opener=opener, throttled=False, verify=True)
    text = verifying['body']['messages'][0]['content'][0]['text']
    assert 'do not infer' in text.lower()
    schema = verifying['body']['response_format']['json_schema']['schema']
    assert schema['type'] == 'array'
    assert 'printed_price' in schema['items']['properties']


# The guard above is real, but it is UNMEASURED on live input: it has only ever
# run against a stub verifier, so nobody knows how many of a card's TRUE prices
# it nulls as collateral. Founder call of 2026-08-02 -- ship it OFF and leave
# gate 1's split-screen human check as the backstop until that number exists.
# The upload-quality rule covers 25 of the 27 fabrications; the other 2 (a blank
# price cell on a perfectly legible page) are what the guard is still here for.

def test_verification_is_off_by_default_so_a_read_price_is_kept_as_read():
    rows = [{'name': 'Black Tea', 'raw_name': 'Black Tea', 'price': 50,
             'raw_price_text': '50', 'source_page': 1}]
    out = extract_nv.extract_menu(_png(), 'image/png', model='m', api_key='k',
                                  opener=_opener(_chat(rows), observed=[]),
                                  throttled=False)
    assert out['items'][0]['price'] == 50
    assert 'price_unverified' not in out['items'][0]


def test_verification_off_costs_one_request_per_page_not_two():
    """Extraction latency is an open risk in the spec: ~110 s to extract and
    ~34 s to verify, so leaving the guard on doubles the calls on every card."""
    names = []

    def opener(req, timeout=None):
        body = json.loads(req.data.decode())
        names.append(body['response_format']['json_schema']['name'])
        return io.BytesIO(json.dumps(_chat(ONE_ITEM)).encode())

    extract_nv.extract_menu(_png(), 'image/png', model='m', api_key='k',
                            opener=opener, throttled=False)
    assert names == ['menu_items']


def test_verification_can_be_forced_on_per_call_without_touching_settings():
    """The live-run script and any measurement harness need the guard on while
    the suite and production stay on the default."""
    rows = [{'name': 'Red Bull Yellow', 'raw_name': 'Red Bull Yellow',
             'price': 100, 'raw_price_text': '100', 'source_page': 1}]
    out = extract_nv.extract_menu(_png(), 'image/png', model='m', api_key='k',
                                  opener=_opener(_chat(rows), observed=[]),
                                  throttled=False, verify=True)
    assert out['items'][0]['price'] is None
    assert out['items'][0]['price_unverified'] is True


def test_the_setting_turns_verification_back_on_fleet_wide(settings):
    """One switch flips it for the workers too, once the collateral number
    exists and the founder decides to trust it."""
    settings.MENU_PRICE_VERIFY = True
    rows = [{'name': 'Red Bull Yellow', 'raw_name': 'Red Bull Yellow',
             'price': 100, 'raw_price_text': '100', 'source_page': 1}]
    # No `verify=` on purpose -- the setting alone must decide, which is what a
    # Celery worker gets.
    out = extract_nv.extract_menu(_png(), 'image/png', model='m', api_key='k',
                                  opener=_opener(_chat(rows), observed=[]),
                                  throttled=False)
    assert out['items'][0]['price'] is None
    assert out['items'][0]['price_unverified'] is True


def test_the_display_name_is_composed_in_code_from_base_and_variant():
    """The model leaves `name` as the shared printed line on all three variants
    and expresses the difference only in `variant_label`."""
    rows = [{'name': 'Steam : Veg / Chicken / Buff', 'raw_name': 'Steam',
             'base_name': 'Steam Momo', 'variant_label': 'Buff', 'price': 250,
             'source_page': 1}]
    out = extract_nv.extract_menu(_png(), 'image/png', model='m', api_key='k',
                                  opener=_opener(_chat(rows)), throttled=False)
    assert out['items'][0]['name'] == 'Steam Momo (Buff)'


def test_a_name_with_no_variant_is_left_alone():
    out = extract_nv.extract_menu(_png(), 'image/png', model='m', api_key='k',
                                  opener=_opener(_chat(ONE_ITEM)), throttled=False)
    assert out['items'][0]['name'] == 'Black Tea'


def test_currency_is_forced_to_npr_whatever_the_model_says():
    """The unguided run volunteered `INR`, which is printed nowhere on a Nepali
    card. Currency is never inferred from a document."""
    rows = [dict(ONE_ITEM[0], currency='INR')]
    out = extract_nv.extract_menu(_png(), 'image/png', model='m', api_key='k',
                                  opener=_opener(_chat(rows)), throttled=False)
    assert out['items'][0]['currency'] == 'NPR'


def test_each_page_is_a_separate_call_and_rows_carry_their_page_number():
    import fitz
    doc = fitz.open()
    for _ in range(2):
        doc.new_page()
    calls = []

    def opener(req, timeout=None):
        body = json.loads(req.data.decode())
        calls.append(body)
        name = (body.get('response_format', {})
                    .get('json_schema', {}).get('name'))
        if name == 'prices':
            return io.BytesIO(json.dumps(_chat([{'printed_price': '50'}])).encode())
        return io.BytesIO(json.dumps(_chat(ONE_ITEM)).encode())

    out = extract_nv.extract_menu(doc.tobytes(), 'application/pdf', model='m',
                                  api_key='k', opener=opener, throttled=False)
    extractions = [c for c in calls
                   if c['response_format']['json_schema']['name'] == 'menu_items']
    assert len(extractions) == 2
    assert sorted(i['source_page'] for i in out['items']) == [1, 2]


def test_page_type_is_decided_from_the_item_count_not_asked_of_the_model():
    """A page that yields items is a menu page; one that yields none is flagged
    for a human rather than guessed at."""
    import fitz
    doc = fitz.open()
    for _ in range(2):
        doc.new_page()
    replies = [_chat(ONE_ITEM), _chat([{'printed_price': '50'}]), _chat([])]

    def opener(req, timeout=None):
        return io.BytesIO(json.dumps(replies.pop(0)).encode())

    out = extract_nv.extract_menu(doc.tobytes(), 'application/pdf', model='m',
                                  api_key='k', opener=opener, throttled=False)
    types = {p['index']: p['page_type'] for p in out['pages']}
    assert types == {1: 'menu', 2: 'unknown'}


def test_a_page_that_returns_unparseable_text_fails_loudly():
    """Silently dropping a page would publish a menu missing a whole section."""
    def opener(req, timeout=None):
        return io.BytesIO(json.dumps(
            {'choices': [{'message': {'content': 'I am afraid I cannot'}}]}).encode())

    with pytest.raises(ValueError, match='did not return JSON'):
        extract_nv.extract_menu(_png(), 'image/png', model='m', api_key='k',
                                opener=opener, throttled=False)


def test_a_missing_key_is_refused_before_any_request_is_built():
    with pytest.raises(ValueError, match='NVIDIA API key'):
        extract_nv.extract_menu(_png(), 'image/png', model='m', api_key='',
                                opener=_opener(_chat(ONE_ITEM)), throttled=False)


def test_every_page_draws_on_the_rate_budget_separately():
    """Every test above passes `throttled=False`, so none of them would notice
    the throttle being unwired. Pacing is per REQUEST, not per document: on the
    shipping default a 3-page document is 3 calls against a 6/min budget."""
    import fitz
    doc = fitz.open()
    for _ in range(3):
        doc.new_page()

    with patch('menu.pipeline.throttle.acquire') as acquire:
        extract_nv.extract_menu(doc.tobytes(), 'application/pdf', model='m',
                                api_key='k', opener=_opener(_chat(ONE_ITEM)))
    assert acquire.call_count == 3


def test_the_guard_doubles_what_a_document_costs_against_the_budget():
    """Why it is off by default. With verification on, every page is a second
    request too, so a real 5-page card is 10 calls against a 6/min budget --
    the pacing alone adds minutes before any inference time."""
    import fitz
    doc = fitz.open()
    for _ in range(3):
        doc.new_page()

    with patch('menu.pipeline.throttle.acquire') as acquire:
        extract_nv.extract_menu(doc.tobytes(), 'application/pdf', model='m',
                                api_key='k', opener=_opener(_chat(ONE_ITEM)),
                                verify=True)
    assert acquire.call_count == 6
