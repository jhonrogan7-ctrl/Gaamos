import base64
import io
import json

import pytest

from menu.pipeline import generate_flux as generate_flux_module
from menu.pipeline.generate_flux import generate_image


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(payload, captured):
    def fake_opener(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.headers)
        captured["body"] = json.loads(req.data.decode())
        return FakeResp(json.dumps(payload).encode())
    return fake_opener


def test_generate_image_decodes_artifact_base64():
    raw = b"\xff\xd8\xffFAKEJPEG"
    captured = {}
    payload = {"artifacts": [{"base64": base64.b64encode(raw).decode(),
                              "finishReason": "SUCCESS", "seed": 5}]}

    out = generate_image("a bowl of dhido", api_key="KEY",
                         model="black-forest-labs/flux.2-klein-4b",
                         opener=_opener(payload, captured))

    assert out == raw
    assert captured["url"] == ("https://ai.api.nvidia.com/v1/genai/"
                               "black-forest-labs/flux.2-klein-4b")
    assert captured["body"]["prompt"] == "a bowl of dhido"


def test_key_travels_in_authorization_header_not_the_url():
    """Gemini puts the key in the query string; this endpoint must not."""
    captured = {}
    payload = {"artifacts": [{"base64": base64.b64encode(b"x").decode()}]}

    generate_image("p", api_key="SECRET", model="m",
                   opener=_opener(payload, captured))

    assert "SECRET" not in captured["url"]
    assert captured["headers"]["Authorization"] == "Bearer SECRET"


def test_omits_image_key_which_the_api_rejects_when_empty():
    """`"image": [""]` returns 422 — text-to-image is selected by omission."""
    captured = {}
    payload = {"artifacts": [{"base64": base64.b64encode(b"x").decode()}]}

    generate_image("p", api_key="K", model="m", opener=_opener(payload, captured))

    assert "image" not in captured["body"]


def test_passes_through_generation_params():
    captured = {}
    payload = {"artifacts": [{"base64": base64.b64encode(b"x").decode()}]}

    generate_image("p", api_key="K", model="m", width=512, height=768,
                   seed=42, steps=8, opener=_opener(payload, captured))

    body = captured["body"]
    assert (body["width"], body["height"]) == (512, 768)
    assert (body["seed"], body["steps"]) == (42, 8)


def test_missing_key_raises():
    with pytest.raises(ValueError, match="NVIDIA_API_KEY"):
        generate_image("p", api_key="", model="m", opener=lambda *a, **k: None)


def test_content_filtered_raises_a_distinct_error():
    """The endpoint answers 200 with an empty artifact and finishReason
    CONTENT_FILTERED when its safety filter declines a prompt. That verdict is
    deterministic — same prompt, any seed, same refusal — so callers must be
    able to tell it apart from a transient failure and not retry it."""
    payload = {"artifacts": [{"base64": "", "finishReason": "CONTENT_FILTERED",
                              "seed": 0}]}

    with pytest.raises(generate_flux_module.ContentFiltered):
        generate_image("p", api_key="K", model="m", opener=_opener(payload, {}))


def test_content_filtered_is_not_confused_with_a_transient_failure():
    with pytest.raises(ValueError, match="no image artifact"):
        generate_image("p", api_key="K", model="m",
                       opener=_opener({"artifacts": []}, {}))


def test_response_without_artifact_raises():
    captured = {}
    with pytest.raises(ValueError, match="no image artifact"):
        generate_image("p", api_key="K", model="m",
                       opener=_opener({"artifacts": []}, captured))
