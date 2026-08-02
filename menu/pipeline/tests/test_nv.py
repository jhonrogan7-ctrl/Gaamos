"""The shared transport, and the one thing about this host that surprised us.

`guided_json` exists because the NIM-native `nvext.guided_json` is accepted and
then silently ignored by `integrate.api.nvidia.com`. Measured 2026-08-02: a
vision request carrying it came back byte-identical to one carrying no guidance
at all, and the text model answered in prose. These tests pin the mechanism that
actually works so a future reader does not "simplify" it back to `nvext`.
"""
import json

from menu.pipeline import nv


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
