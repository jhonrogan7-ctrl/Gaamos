"""Generate an image via NVIDIA's hosted FLUX endpoint; returns raw image bytes.

Same contract as `generate.py` (Gemini) so the two are drop-in alternatives:
`generate_image(prompt) -> bytes`. Key + model default to Django settings
(NVIDIA_API_KEY / NVIDIA_IMAGE_MODEL, sourced from .env).

Unlike Gemini the credential travels in an Authorization header, not the query
string, and the response carries base64 under `artifacts[]`.
"""
import base64
import json
import urllib.request
import zlib

_ENDPOINT = "https://ai.api.nvidia.com/v1/genai/{model}"


class ContentFiltered(ValueError):
    """The endpoint's safety filter declined the prompt: HTTP 200, an empty
    artifact, finishReason CONTENT_FILTERED. Deterministic — the same prompt is
    refused at every seed — so callers should move on rather than retry."""


# NVIDIA rejects a seed outside signed 32-bit range.
_SEED_MODULUS = 2 ** 31


def seed_for(key, attempt=0):
    """A stable per-item seed.

    The seed was hardcoded to 0 for every image in a venue, so a section came
    back as the same plate on the same table under the same window — which at
    menu-thumbnail size reads as one photo repeated. Deriving it from the item
    key keeps runs reproducible while giving each item its own composition;
    `attempt` is what a re-roll advances so it cannot reproduce the image it is
    replacing.
    """
    return (zlib.crc32(key.encode()) + attempt) % _SEED_MODULUS


def generate_image(prompt, *, api_key=None, model=None, width=1024, height=1024,
                   seed=0, steps=8, opener=urllib.request.urlopen):
    """Generate an image from `prompt` via NVIDIA FLUX; return raw image bytes."""
    if api_key is None or model is None:
        from django.conf import settings
        api_key = api_key or settings.NVIDIA_API_KEY
        model = model or settings.NVIDIA_IMAGE_MODEL
    if not api_key:
        raise ValueError("No NVIDIA API key: pass api_key= or set NVIDIA_API_KEY in .env")
    url = _ENDPOINT.format(model=model)
    # No `image` key: sending an empty one is rejected 422 "Image has been
    # provided in the invalid form" — omission is what selects text-to-image.
    body = {"prompt": prompt, "width": width, "height": height,
            "seed": seed, "steps": steps}
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "Authorization": f"Bearer {api_key}"}, method="POST")
    with opener(req, timeout=180) as resp:
        data = json.loads(resp.read().decode())
    artifacts = data.get("artifacts") or []
    for art in artifacts:
        if art.get("base64"):
            return base64.b64decode(art["base64"])
    if any(a.get("finishReason") == "CONTENT_FILTERED" for a in artifacts):
        raise ContentFiltered("NVIDIA safety filter declined this prompt")
    raise ValueError("NVIDIA response contained no image artifact")
