"""Gemini vision adapter: extract a cafe menu document into structured JSON.
Single structured-output vision call (not an agent). `opener` is injectable so
tests run without network. Mirrors generate.py / embed.py."""
import base64
import json
import urllib.request

_ENDPOINT = ("https://generativelanguage.googleapis.com/v1beta/models/"
             "{model}:generateContent?key={key}")

_PROMPT = (
    "You are given a restaurant/cafe menu document. Extract every menu item. "
    "Return JSON only, matching the schema: an object with a `categories` array; "
    "each category has `name` and an `items` array; each item has `name`, "
    "`description` (empty string if none), and `price` (integer rupees, or null if "
    "unreadable). Do not invent items; transcribe faithfully.")

_SCHEMA = {
    "type": "object",
    "properties": {
        "categories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "description": {"type": "string"},
                                "price": {"type": "integer", "nullable": True},
                            },
                            "required": ["name"],
                        },
                    },
                },
                "required": ["name", "items"],
            },
        },
    },
    "required": ["categories"],
}


def extract_menu(file_bytes, mime, *, api_key=None, model=None,
                 opener=urllib.request.urlopen):
    if api_key is None or model is None:
        from django.conf import settings
        api_key = api_key or settings.GEMINI_API_KEY
        model = model or settings.GEMINI_VISION_MODEL
    if not api_key:
        raise ValueError("No Gemini API key: pass api_key= or set GEMINI_API_KEY in .env")
    url = _ENDPOINT.format(model=model, key=api_key)
    body = {
        "contents": [{"parts": [
            {"inline_data": {"mime_type": mime,
                             "data": base64.b64encode(file_bytes).decode()}},
            {"text": _PROMPT},
        ]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _SCHEMA,
        },
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with opener(req, timeout=180) as resp:
        data = json.loads(resp.read().decode())
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)
