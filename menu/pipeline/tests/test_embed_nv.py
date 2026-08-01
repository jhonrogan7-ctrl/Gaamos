"""The catalog's embedding adapter.

`nvidia/nv-embedqa-e5-v5` is retrieval-tuned with asymmetric query/passage
encoding, which is exactly the "is this the same dish" job -- so `input_type` is
part of the contract, not a detail.
"""
import io
import json

import pytest

from menu.pipeline import embed_nv, item_embed

captured = {}


def _opener(vector):
    def opener(req, timeout=None):
        captured['body'] = json.loads(req.data.decode())
        return io.BytesIO(json.dumps(
            {'data': [{'embedding': list(vector)}]}).encode())
    return opener


def test_it_returns_the_vector_the_catalog_column_stores():
    vec = embed_nv.embed('black tea', model='m', api_key='k',
                         opener=_opener([0.1] * 1024), throttled=False)
    assert len(vec) == item_embed.DIMENSIONS


def test_a_passage_and_a_query_are_encoded_differently():
    """Asymmetric encoding is the whole reason this model was chosen; sending
    everything as one type throws that away silently."""
    embed_nv.embed('black tea', kind='passage', model='m', api_key='k',
                   opener=_opener([0.1] * 1024), throttled=False)
    assert captured['body']['input_type'] == 'passage'
    embed_nv.embed('black tea', kind='query', model='m', api_key='k',
                   opener=_opener([0.1] * 1024), throttled=False)
    assert captured['body']['input_type'] == 'query'


def test_truncate_end_is_sent_so_a_long_description_does_not_error():
    embed_nv.embed('x' * 5000, model='m', api_key='k',
                   opener=_opener([0.1] * 1024), throttled=False)
    assert captured['body']['truncate'] == 'END'


def test_an_unknown_input_type_is_refused_rather_than_sent():
    with pytest.raises(ValueError, match='input_type'):
        embed_nv.embed('black tea', kind='sideways', model='m', api_key='k',
                       opener=_opener([0.1] * 1024), throttled=False)


def test_a_wrong_width_vector_is_refused_by_the_seam():
    """A vector from another model does not share this space. 77 Gemini vectors
    in this column are exactly why the seam raises."""
    with pytest.raises(ValueError, match='768'):
        item_embed.embed_text(
            'black tea',
            embedder=lambda t: embed_nv.embed(t, model='m', api_key='k',
                                              opener=_opener([0.1] * 768),
                                              throttled=False))


def test_the_provider_is_wired_when_a_model_and_key_are_configured(settings):
    settings.NVIDIA_API_KEY = 'k'
    settings.NVIDIA_EMBED_MODEL = 'nvidia/nv-embedqa-e5-v5'
    assert item_embed.resolve_provider() is not None


def test_no_key_means_no_provider_rather_than_an_error(settings):
    """Spec D6: every AI layer is optional. No key switches the vector layer
    off; layers 0-2 of the matcher carry on."""
    settings.NVIDIA_API_KEY = ''
    assert item_embed.resolve_provider() is None
