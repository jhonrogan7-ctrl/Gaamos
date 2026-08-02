"""NVIDIA text completions, with guided JSON when a schema is given.

Phase 3's matcher layer 4 adjudicates ambiguous candidate pairs in batches
through this; phase 4 uses it for prompt authoring and category-icon choice.

`temperature=0.0` throughout: every job this serves is a decision, not a piece
of writing, and a decision that changes between runs cannot be regression-tested.
"""
import json
import urllib.request

from menu.pipeline import nv, throttle


def _model():
    from django.conf import settings
    return settings.NVIDIA_TEXT_MODEL


def complete(prompt, *, schema=None, system=None, model=None, api_key=None,
             opener=urllib.request.urlopen, throttled=True):
    """-> parsed JSON when `schema` is given, else the raw assistant text."""
    model = model or _model()
    if throttled:
        throttle.acquire(model)
    messages = []
    if system:
        messages.append({'role': 'system', 'content': system})
    messages.append({'role': 'user', 'content': prompt})
    body = {'model': model, 'messages': messages, 'temperature': 0.0,
            'max_tokens': 4096}
    if schema is not None:
        # Guided decoding, never a schema pasted into the prompt: the vision
        # probe measured that difference at 26/36 items versus 36/36.
        body.update(nv.guided_json(schema, name='decision'))
    text = nv.message_text(nv.post('/chat/completions', body, key=api_key,
                                   opener=opener))
    if schema is None:
        return text
    try:
        return json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f'text model did not return JSON: {str(text)[:200]!r}') from exc
