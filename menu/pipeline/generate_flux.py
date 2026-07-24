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

_ENDPOINT = "https://ai.api.nvidia.com/v1/genai/{model}"


class ContentFiltered(ValueError):
    """The endpoint's safety filter declined the prompt: HTTP 200, an empty
    artifact, finishReason CONTENT_FILTERED. Deterministic — the same prompt is
    refused at every seed — so callers should move on rather than retry."""


def generate_image(prompt, *, api_key=None, model=None, width=1024, height=1024,
                   seed=0, steps=4, opener=urllib.request.urlopen):
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
