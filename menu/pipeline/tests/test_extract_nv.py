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


def _opener(payload):
    """Stand in for the endpoint; record what the adapter sent."""
    def opener(req, timeout=None):
        captured['url'] = req.full_url
        captured['headers'] = {k.lower(): v for k, v in req.headers.items()}
        captured['body'] = json.loads(req.data.decode())
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
    """Only a parent row -- one whose variants carry the prices -- is dropped. A
    lone unpriced item is a real row that gate 1 asks a human about."""
    rows = [{'name': 'Soup of the Day', 'raw_name': 'Soup of the Day',
             'price': None, 'source_page': 1}]
    out = extract_nv.extract_menu(_png(), 'image/png', model='m', api_key='k',
                                  opener=_opener(_chat(rows)), throttled=False)
    assert len(out['items']) == 1


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
        calls.append(json.loads(req.data.decode()))
        return io.BytesIO(json.dumps(_chat(ONE_ITEM)).encode())

    out = extract_nv.extract_menu(doc.tobytes(), 'application/pdf', model='m',
                                  api_key='k', opener=opener, throttled=False)
    assert len(calls) == 2
    assert sorted(i['source_page'] for i in out['items']) == [1, 2]


def test_page_type_is_decided_from_the_item_count_not_asked_of_the_model():
    """A page that yields items is a menu page; one that yields none is flagged
    for a human rather than guessed at."""
    import fitz
    doc = fitz.open()
    for _ in range(2):
        doc.new_page()
    replies = [_chat(ONE_ITEM), _chat([])]

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
    the throttle being unwired. Pacing is per REQUEST, not per document: a real
    card is 5 pages, so one scan is 5 calls against a 6/min budget."""
    import fitz
    doc = fitz.open()
    for _ in range(3):
        doc.new_page()

    def opener(req, timeout=None):
        return io.BytesIO(json.dumps(_chat(ONE_ITEM)).encode())

    with patch('menu.pipeline.throttle.acquire') as acquire:
        extract_nv.extract_menu(doc.tobytes(), 'application/pdf', model='m',
                                api_key='k', opener=opener)
    assert acquire.call_count == 3
