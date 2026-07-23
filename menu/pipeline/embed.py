"""Gemini text-embedding adapter for the image library's semantic match.

Embeds a caption or an item's text into a 768-d vector (text-embedding-004).
Key + model default to Django settings (from .env) so callers can omit them.
Provider-agnostic surface, mirroring generate.py — swap the endpoint to change
backends. `opener` is injectable so tests run without network."""
import json
import urllib.request

_ENDPOINT = ("https://generativelanguage.googleapis.com/v1beta/models/"
             "{model}:embedContent?key={key}")


def embed(text, *, api_key=None, model=None, opener=urllib.request.urlopen):
    if api_key is None or model is None:
        from django.conf import settings
        api_key = api_key or settings.GEMINI_API_KEY
        model = model or settings.GEMINI_EMBED_MODEL
    if not api_key:
        raise ValueError("No Gemini API key: pass api_key= or set GEMINI_API_KEY in .env")
    url = _ENDPOINT.format(model=model, key=api_key)
    body = {"model": f"models/{model}",
            "content": {"parts": [{"text": text}]}}
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with opener(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    return list(data["embedding"]["values"])
