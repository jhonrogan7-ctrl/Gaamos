"""The one place that knows how to talk to integrate.api.nvidia.com.

All three adapters (`extract_nv`, `embed_nv`, `text_nv`) go through here, so a
transport fix -- an auth header change, a new error shape -- lands once rather
than three times. FLUX image generation is NOT here: it lives on a different
host (`ai.api.nvidia.com/v1/genai`) and already works, so `generate_flux.py`
keeps its own transport.
"""
import json
import urllib.error
import urllib.request


class NotAvailable(RuntimeError):
    """This account cannot invoke this model.

    Distinct from a transport failure on purpose: two embedding models appear in
    `GET /v1/models` and return 404 'Not found for account' when called, so
    listing is not availability and a caller may want to switch its layer off
    rather than retry.
    """


def api_key():
    from django.conf import settings
    return settings.NVIDIA_API_KEY


def base_url():
    from django.conf import settings
    return settings.NVIDIA_BASE_URL.rstrip('/')


def post(path, body, *, key=None, opener=urllib.request.urlopen, timeout=300):
    """POST JSON to `path` (e.g. '/chat/completions'); return the parsed reply."""
    key = api_key() if key is None else key
    if not key:
        raise ValueError(
            'No NVIDIA API key: pass api_key= or set NVIDIA_API_KEY in .env')
    req = urllib.request.Request(
        f'{base_url()}{path}', data=json.dumps(body).encode(),
        headers={'Content-Type': 'application/json',
                 'Accept': 'application/json',
                 'Authorization': f'Bearer {key}'}, method='POST')
    try:
        with opener(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 404):
            raise NotAvailable(
                f'{body.get("model", "?")}: HTTP {exc.code} for this account') from exc
        raise


def guided_json(schema, *, name='payload'):
    """The body fragment that makes this host constrain output to `schema`.

    Use this rather than writing the field by hand. `nvext.guided_json` -- the
    NIM-native form, and the one every NVIDIA NIM example shows -- is accepted
    and then SILENTLY IGNORED by `integrate.api.nvidia.com`. Measured 2026-08-02
    against both chat models:

    - vision, blank image, `nvext.guided_json`: `1. BLT 2. BLT 3. BLT ...` to
      `finish_reason: length` -- byte-identical to the same request carrying no
      guidance at all, which is how we know it is a no-op and not merely weak.
    - vision, same request via `response_format`: `[  ]`, `finish_reason: stop`,
      4 completion tokens.
    - text, `nvext.guided_json`: prose that does not parse. Via
      `response_format`: `{"verdict": "same", "confidence": 0.9}`.

    Guided decoding itself is not optional -- 36/36 items with it against 26/36
    without (probe 2026-07-30), the ten lost being exactly the protein variants.
    Only the field carrying it changed.
    """
    return {'response_format': {'type': 'json_schema',
                                'json_schema': {'name': name, 'schema': schema}}}


def message_text(reply):
    """The assistant text out of an OpenAI-shaped chat reply."""
    try:
        return reply['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f'unexpected chat response shape: {reply!r}') from exc
