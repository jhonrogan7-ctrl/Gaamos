"""The shared transport, and the one thing about this host that surprised us.

`guided_json` exists because the NIM-native `nvext.guided_json` is accepted and
then silently ignored by `integrate.api.nvidia.com`. Measured 2026-08-02: a
vision request carrying it came back byte-identical to one carrying no guidance
at all, and the text model answered in prose. These tests pin the mechanism that
actually works so a future reader does not "simplify" it back to `nvext`.
"""
import io
import json
import urllib.error

import pytest

from menu.pipeline import nv


def _failing_opener(code, body):
    def opener(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, code, 'Internal Server Error',
                                     {}, io.BytesIO(body.encode()))
    return opener


def test_a_server_error_carries_the_endpoints_explanation_not_just_its_code():
    """Measured 2026-08-02: when the vision model went down, `scan.error` stored
    the bare string 'HTTP Error 500: Internal Server Error' and it took a
    bespoke probe to discover the endpoint had actually said 'EngineCore
    encountered an issue'. The body is the whole diagnostic -- without it every
    500 looks like every other one, including the ones we cause ourselves (a
    `price_source` enum in the item schema returns 500 too)."""
    opener = _failing_opener(500, json.dumps(
        {'error': {'message': 'EngineCore encountered an issue.'}}))
    with pytest.raises(urllib.error.HTTPError, match='EngineCore'):
        nv.post('/chat/completions', {'model': 'm'}, key='k', opener=opener)


def test_a_server_error_is_still_an_httperror_with_its_status_intact():
    """Callers distinguish 'this account cannot reach the model' (NotAvailable)
    from 'the host broke', and `probe_models` prints the code. Enriching the
    message must not change the type or lose the status."""
    opener = _failing_opener(500, 'upstream exploded')
    with pytest.raises(urllib.error.HTTPError) as caught:
        nv.post('/chat/completions', {'model': 'm'}, key='k', opener=opener)
    assert caught.value.code == 500


def test_an_unavailable_model_is_still_reported_as_not_available():
    """The 403/404 mapping predates this and has never had a test."""
    opener = _failing_opener(404, 'not found')
    with pytest.raises(nv.NotAvailable, match='mymodel'):
        nv.post('/chat/completions', {'model': 'mymodel'}, key='k', opener=opener)


def test_guided_json_asks_through_response_format_not_nvext():
    """`nvext.guided_json` is a no-op on this host -- a request carrying it is
    indistinguishable from an unguided one (vision looped to max_tokens
    identically with and without it). `response_format` is honoured by both
    chat models."""
    fragment = nv.guided_json({'type': 'array'})
    assert fragment['response_format']['type'] == 'json_schema'
    assert fragment['response_format']['json_schema']['schema'] == {'type': 'array'}


def test_guided_json_never_emits_nvext():
    """Pinned as a negative on purpose: sending `nvext` costs nothing but tells
    every future reader that guidance is handled, when it is not."""
    assert 'nvext' not in json.dumps(nv.guided_json({'type': 'object'}))


def test_the_schema_carries_a_name_because_the_endpoint_requires_one():
    named = nv.guided_json({'type': 'array'}, name='menu_items')
    assert named['response_format']['json_schema']['name'] == 'menu_items'
