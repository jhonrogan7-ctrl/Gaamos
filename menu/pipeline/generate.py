import base64
import json
import urllib.request

_ENDPOINT = ("https://generativelanguage.googleapis.com/v1beta/models/"
             "{model}:generateContent?key={key}")


def generate_image(prompt, *, api_key=None, model=None,
                   opener=urllib.request.urlopen):
    """Generate an image from `prompt` via Gemini; return raw image bytes.

    `api_key` and `model` fall back to Django settings (GEMINI_API_KEY /
    GEMINI_IMAGE_MODEL, sourced from .env) so callers can omit them."""
    if api_key is None or model is None:
        from django.conf import settings
        api_key = api_key or settings.GEMINI_API_KEY
        model = model or settings.GEMINI_IMAGE_MODEL
    if not api_key:
        raise ValueError("No Gemini API key: pass api_key= or set GEMINI_API_KEY in .env")
    url = _ENDPOINT.format(model=model, key=api_key)
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"]}}
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with opener(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    for part in data["candidates"][0]["content"]["parts"]:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            return base64.b64decode(inline["data"])
    raise ValueError("Gemini response contained no inline image data")
