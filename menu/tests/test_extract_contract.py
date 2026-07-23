"""The vision adapter's request shape and response contract. No network: the
opener is injected, exactly as generate.py and embed.py do it."""
import json

from menu.dietary import DIETARY_VOCAB
from menu.pipeline import extract

PAYLOAD = {
    "pages": [{"index": 1, "page_type": "menu", "confidence": 0.94}],
    "items": [{"name": "Black Tea", "raw_name": "Black Tea", "price": 50,
               "source_page": 1, "confidence": 0.9}],
}


class _FakeResp:
    def __init__(self, body):
        self._body = body

    def read(self):
        return json.dumps(self._body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _opener(captured):
    def open_it(req, timeout=None):
        captured['body'] = json.loads(req.data.decode())
        captured['url'] = req.full_url
        return _FakeResp({"candidates": [{"content": {"parts": [
            {"text": json.dumps(PAYLOAD)}]}}]})
    return open_it


def test_returns_flat_items_and_page_manifest():
    captured = {}
    got = extract.extract_menu(b'PDF', 'application/pdf', api_key='k', model='m',
                               opener=_opener(captured))
    assert got == PAYLOAD
    assert got['items'][0]['name'] == 'Black Tea'
    assert got['pages'][0]['page_type'] == 'menu'


def test_request_carries_inline_data_and_response_schema():
    captured = {}
    extract.extract_menu(b'PDF', 'application/pdf', api_key='k', model='m',
                        opener=_opener(captured))
    parts = captured['body']['contents'][0]['parts']
    assert parts[0]['inline_data']['mime_type'] == 'application/pdf'
    cfg = captured['body']['generationConfig']
    assert cfg['responseMimeType'] == 'application/json'
    assert set(cfg['responseSchema']['required']) == {'pages', 'items'}


def test_schema_declares_the_canonical_item_fields():
    props = extract._SCHEMA['properties']['items']['items']['properties']
    for field in ('name', 'base_name', 'variant_label', 'description', 'category',
                  'price', 'currency', 'dietary_tags', 'tags', 'raw_name',
                  'raw_price_text', 'raw_section', 'split_from', 'source_page',
                  'confidence'):
        assert field in props, field


def test_schema_constrains_page_type():
    page_props = extract._SCHEMA['properties']['pages']['items']['properties']
    assert set(page_props['page_type']['enum']) == {
        'menu', 'signage', 'contact', 'screenshot', 'unknown'}


def test_prompt_states_the_rules_the_validators_enforce():
    prompt = extract._PROMPT.lower()
    assert 'split_from' in prompt          # multi-product line rule
    assert 'variant_label' in prompt       # multi-price row rule
    assert 'never add synonyms' in prompt  # D6
    for value in DIETARY_VOCAB:
        assert value in prompt             # D7 vocabulary is spelled out
