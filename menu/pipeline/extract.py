"""Gemini vision adapter: extract a cafe menu document into structured JSON.
Single structured-output vision call (not an agent). `opener` is injectable so
tests run without network. Mirrors generate.py / embed.py."""
import base64
import json
import urllib.request

_ENDPOINT = ("https://generativelanguage.googleapis.com/v1beta/models/"
             "{model}:generateContent?key={key}")

_PROMPT = (
    "You are given a restaurant/cafe menu document. Return JSON only.\n"
    "1. Transcribe faithfully. Never invent an item that is not printed.\n"
    "2. If one printed line names several products (for example "
    "'Coke/Fanta/Sprite'), emit ONE item per product and set `split_from` to the "
    "full printed line.\n"
    "3. If a row carries several prices - a matrix with column headers such as "
    "'60ml | Qtr.' or 'HALF | FULL', or an inline '200/260' - emit ONE item per "
    "price. Set `base_name` to the shared product name, `variant_label` to that "
    "price's label, and `name` to the full display name.\n"
    "4. `tags` must contain ONLY words that appear in that item's printed name. "
    "Never add synonyms, translations or inferred ingredients.\n"
    "5. `dietary_tags` may only use these values: "
    "veg, vegan, egg, chicken, buff, pork, fish, mutton. Infer them from the "
    "section heading, any veg/non-veg glyph, and the item name.\n"
    "6. `price` is an integer or null. Never guess a price that is not printed.\n"
    "7. Copy the verbatim printed text into `raw_name`, `raw_price_text` and "
    "`raw_section`.\n"
    "8. Classify every page in `pages`: `menu` for a page listing items, "
    "`signage` for artwork or a signboard, `contact` for WiFi/phone/QR/payment "
    "pages, `screenshot` for anything showing browser or phone UI.\n"
    "9. Where a price column is misaligned or ambiguous, return a low "
    "`confidence` rather than a guess.")

_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "base_name": {"type": "string"},
        "variant_label": {"type": "string"},
        "description": {"type": "string"},
        "category": {"type": "string"},
        "price": {"type": "integer", "nullable": True},
        "currency": {"type": "string"},
        "dietary_tags": {"type": "array", "items": {"type": "string"}},
        "tags": {"type": "array", "items": {"type": "string"}},
        "raw_name": {"type": "string"},
        "raw_price_text": {"type": "string"},
        "raw_section": {"type": "string"},
        "split_from": {"type": "string"},
        "source_page": {"type": "integer"},
        "confidence": {"type": "number"},
    },
    "required": ["name", "raw_name", "source_page"],
}

_SCHEMA = {
    "type": "object",
    "properties": {
        "pages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "page_type": {"type": "string", "enum": [
                        "menu", "signage", "contact", "screenshot", "unknown"]},
                    "confidence": {"type": "number"},
                },
                "required": ["index", "page_type"],
            },
        },
        "items": {"type": "array", "items": _ITEM_SCHEMA},
    },
    "required": ["pages", "items"],
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
