import base64
import json
import urllib.request

_ENDPOINT = ("https://generativelanguage.googleapis.com/v1beta/models/"
             "{model}:generateContent?key={key}")


def generate_image(prompt, *, api_key, model="gemini-2.5-flash-image",
                   opener=urllib.request.urlopen):
    """Generate an image from `prompt` via Gemini; return raw image bytes."""
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
