"""NVIDIA embeddings for the item catalog.

`nvidia/nv-embedqa-e5-v5`, invocation-verified at 1024-d on 2026-07-30. It is
retrieval-tuned with asymmetric query/passage encoding -- a stored library entry
is a `passage`, an incoming scanned row is a `query` -- which is exactly the
matcher's job, so `input_type` is part of the contract rather than a detail.

`ImageAsset` captions do NOT come here: that pool is 768-d and Gemini-shaped,
and `menu/pipeline/embed.py` remains its adapter.
"""
import urllib.request

from menu.pipeline import nv, throttle

_KINDS = ('query', 'passage')


def _model():
    from django.conf import settings
    return settings.NVIDIA_EMBED_MODEL


def embed(text, *, kind='passage', model=None, api_key=None,
          opener=urllib.request.urlopen, throttled=True):
    """-> the embedding vector for `text`."""
    if kind not in _KINDS:
        raise ValueError(f'input_type must be one of {_KINDS}, got {kind!r}')
    model = model or _model()
    if throttled:
        throttle.acquire(model)
    body = {'model': model, 'input': [text], 'input_type': kind,
            'encoding_format': 'float', 'truncate': 'END'}
    reply = nv.post('/embeddings', body, key=api_key, opener=opener, timeout=60)
    try:
        return list(reply['data'][0]['embedding'])
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f'unexpected embeddings response: {reply!r}') from exc
