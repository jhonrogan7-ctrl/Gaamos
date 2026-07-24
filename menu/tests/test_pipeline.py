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


def test_commons_search_parses_and_ranks(monkeypatch):
    import menu.pipeline.find_commons as fc

    payload = {"query": {"pages": {
        "20": {"index": 2, "title": "File:Beta.jpg",
               "imageinfo": [{"thumburl": "https://x/beta.jpg", "mime": "image/jpeg"}]},
        "10": {"index": 1, "title": "File:Alpha.jpg",
               "imageinfo": [{"thumburl": "https://x/alpha.jpg", "mime": "image/jpeg"}]},
        "30": {"index": 3, "title": "File:NoImage.jpg", "imageinfo": [{}]},
    }}}

    class FakeResp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, *a, **k):
        return FakeResp(json.dumps(payload).encode())

    monkeypatch.setattr(fc.urllib.request, "urlopen", fake_urlopen)
    res = fc.search("carlsberg beer bottle")
    # ranked by search index; entries with no thumburl dropped
    assert [t for t, _, _ in res] == ["File:Alpha.jpg", "File:Beta.jpg"]
    assert res[0][1] == "https://x/alpha.jpg"


def test_pexels_search_parses_photos(monkeypatch, settings):
    import menu.pipeline.find_pexels as fp
    settings.PEXELS_API_KEY = "TESTKEY"

    payload = {"photos": [
        {"src": {"large": "https://p/large.jpg", "medium": "https://p/med.jpg"},
         "photographer": "Ada", "alt": "chilli chicken", "url": "https://pexels/1"},
        {"src": {"medium": "https://p/med2.jpg"},
         "photographer": "Bo", "alt": "", "url": "https://pexels/2"},
    ]}
    captured = {}

    class FakeResp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, *a, **k):
        captured["auth"] = req.headers.get("Authorization")
        captured["url"] = req.full_url
        return FakeResp(json.dumps(payload).encode())

    monkeypatch.setattr(fp.urllib.request, "urlopen", fake_urlopen)
    res = fp.search("chilli chicken", per_page=2)
    assert captured["auth"] == "TESTKEY"
    assert "chilli+chicken" in captured["url"]
    assert res[0]["url"] == "https://p/large.jpg"        # prefers 'large'
    assert res[0]["photographer"] == "Ada"
    assert res[1]["url"] == "https://p/med2.jpg"         # falls back to 'medium'


def test_openverse_search_prefers_no_attribution(monkeypatch):
    import menu.pipeline.find_openverse as fo

    calls = []
    cc0 = {"results": [{"url": "https://o/cc0.jpg", "title": "Free",
                        "license": "cc0", "license_version": "1.0",
                        "attribution": "", "creator": "X", "source": "flickr",
                        "foreign_landing_url": "https://land/1"}]}

    class FakeResp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, *a, **k):
        calls.append(req.full_url)
        return FakeResp(json.dumps(cc0).encode())

    monkeypatch.setattr(fo.urllib.request, "urlopen", fake_urlopen)
    res = fo.search("tomato soup")
    # first (cc0/pdm) tier returned results -> stops, one query only
    assert len(calls) == 1
    assert "cc0" in calls[0]
    assert res[0]["url"] == "https://o/cc0.jpg"
    assert res[0]["license"].startswith("cc0")


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
