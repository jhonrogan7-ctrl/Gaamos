"""The text adapter. Phase 3's matcher layer 4 adjudicates in batches through
this; phase 4 authors prompts with it."""
import io
import json

import pytest

from menu.pipeline import text_nv

captured = {}


def _opener(content):
    def opener(req, timeout=None):
        captured['body'] = json.loads(req.data.decode())
        return io.BytesIO(json.dumps(
            {'choices': [{'message': {'content': content}}]}).encode())
    return opener


def test_plain_text_comes_back_as_a_string():
    out = text_nv.complete('name this dish', model='m', api_key='k',
                           opener=_opener('Momo'), throttled=False)
    assert out == 'Momo'


def test_a_schema_makes_it_return_parsed_json():
    out = text_nv.complete('decide', schema={'type': 'object'}, model='m',
                           api_key='k', opener=_opener('{"same": true}'),
                           throttled=False)
    assert out == {'same': True}


def test_a_schema_is_sent_as_guided_json_not_pasted_into_the_prompt():
    """The vision probe measured what pasting a schema into a prompt costs: the
    same model scored 26/36 instead of 36/36. Guided decoding is a transport
    feature, not a wording trick."""
    schema = {'type': 'object', 'properties': {'same': {'type': 'boolean'}}}
    text_nv.complete('decide', schema=schema, model='m', api_key='k',
                     opener=_opener('{"same": true}'), throttled=False)
    assert captured['body']['nvext']['guided_json'] == schema
    assert 'properties' not in captured['body']['messages'][-1]['content']


def test_a_system_message_leads_the_conversation():
    text_nv.complete('decide', system='You are terse.', model='m', api_key='k',
                     opener=_opener('ok'), throttled=False)
    roles = [m['role'] for m in captured['body']['messages']]
    assert roles == ['system', 'user']


def test_temperature_is_zero_because_this_is_adjudication_not_writing():
    text_nv.complete('decide', model='m', api_key='k', opener=_opener('ok'),
                     throttled=False)
    assert captured['body']['temperature'] == 0.0


def test_json_that_does_not_parse_under_a_schema_fails_loudly():
    with pytest.raises(ValueError, match='did not return JSON'):
        text_nv.complete('decide', schema={'type': 'object'}, model='m',
                         api_key='k', opener=_opener('sorry'), throttled=False)
