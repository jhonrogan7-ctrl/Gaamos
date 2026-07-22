import base64
import io
import json
from pathlib import Path

from PIL import Image

from menu.pipeline.fixture import build_fixture
from menu.pipeline.generate import generate_image
from menu.pipeline.images import to_thumbnail


def test_to_thumbnail_makes_bounded_webp(tmp_path):
    src = tmp_path / "big.png"
    Image.new("RGB", (2000, 1200), (10, 120, 200)).save(src)
    dest = tmp_path / "out" / "thumb.webp"
    result = to_thumbnail(str(src), str(dest), size=800)
    assert Path(result).exists()
    with Image.open(dest) as im:
        assert im.format == "WEBP"
        assert max(im.size) <= 800


def test_build_fixture_merges_routing_and_defaults_null():
    menu = {"categories": [{"slug": "s", "name": "S", "display_order": 1,
                            "icon_key": "", "hours_note": "", "subcategories": []}],
            "items": [
                {"slug": "wine", "name": "Wine", "cat": "s", "sub": None, "description": "",
                 "price": 500, "tags": [], "popular": False, "featured": False, "order": 1},
                {"slug": "mystery", "name": "Mystery", "cat": "s", "sub": None,
                 "description": "", "price": 300, "tags": [], "popular": False,
                 "featured": False, "order": 2}]}
    routing = {"wine": {"source": "found", "file": "wine.webp",
                        "origin_url": "https://x", "prompt": None}}
    fx = build_fixture("inn", ["restaurant"], menu, routing)
    assert fx["company"] == "inn" and fx["branches"] == ["restaurant"]
    imgs = {i["slug"]: i["image"] for i in fx["items"]}
    assert imgs["wine"]["file"] == "wine.webp" and imgs["wine"]["source"] == "found"
    assert imgs["mystery"] is None
    assert fx["categories"] == menu["categories"]


def test_generate_image_decodes_inline_data():
    raw = b"\x89PNG\r\n\x1a\nFAKEIMAGE"
    b64 = base64.b64encode(raw).decode()
    captured = {}

    class FakeResp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_opener(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())
        payload = {"candidates": [{"content": {"parts": [
            {"inlineData": {"mimeType": "image/png", "data": b64}}]}}]}
        return FakeResp(json.dumps(payload).encode())

    out = generate_image("a boiled egg on a white plate",
                         api_key="KEY", opener=fake_opener)
    assert out == raw
    assert "gemini-2.5-flash-image:generateContent" in captured["url"]
    assert "KEY" in captured["url"]
    assert captured["body"]["contents"][0]["parts"][0]["text"].startswith("a boiled egg")
