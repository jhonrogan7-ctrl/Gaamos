import pytest


@pytest.mark.django_db
def test_base_links_manifest_and_registers_sw(client):
    body = client.get("/en/").content.decode()
    assert 'rel="manifest"' in body
    assert "manifest.webmanifest" in body
    assert "serviceWorker" in body  # registration script present


@pytest.mark.django_db
def test_service_worker_served_at_root_with_scope_header(client):
    resp = client.get("/sw.js")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("application/javascript")
    assert resp["Service-Worker-Allowed"] == "/"
    assert b"gaamos-shell" in resp.content


@pytest.mark.django_db
def test_marketing_base_has_ios_meta(client):
    body = client.get("/en/").content.decode()
    assert "apple-touch-icon" in body
    assert "apple-mobile-web-app-capable" in body


def test_manifests_have_distinct_ids():
    import json
    from django.conf import settings
    pwa = settings.BASE_DIR / "static" / "pwa"
    guest = json.loads((pwa / "manifest.webmanifest").read_text())
    dash = json.loads((pwa / "manifest-dashboard.webmanifest").read_text())
    ops = json.loads((pwa / "manifest-ops.webmanifest").read_text())
    assert guest["id"] == "/" and guest["start_url"] == "/"
    assert dash["id"] == "/dashboard/" and dash["start_url"] == "/dashboard/"
    assert ops["id"] == "/platform/" and ops["start_url"] == "/platform/"
    assert len({guest["id"], dash["id"], ops["id"]}) == 3
    assert guest["name"] == "Gaamos Menu" and dash["name"] == "Gaamos Dashboard"
    assert ops["name"] == "Gaamos Ops"
    # Guest and dashboard share the light icon set; Ops deliberately ships its own
    # black-background variant so the platform app is distinguishable on a home
    # screen full of tenant apps.
    assert {i["src"] for i in guest["icons"]} == {i["src"] for i in dash["icons"]}
    assert {i["src"] for i in ops["icons"]}.isdisjoint({i["src"] for i in guest["icons"]})
    assert all("icon-ops-" in i["src"] for i in ops["icons"])


def test_manifests_declare_any_and_maskable_icons():
    """Every manifest must offer both purposes: 'any' for launchers that draw the
    icon as-is, 'maskable' for Android adaptive icons (which crop to a circle and
    would otherwise clip the mark, or letterbox it into a grey blob)."""
    import json
    from django.conf import settings

    pwa = settings.BASE_DIR / "static" / "pwa"
    for name in ("manifest.webmanifest", "manifest-dashboard.webmanifest", "manifest-ops.webmanifest"):
        icons = json.loads((pwa / name).read_text())["icons"]
        purposes = {i.get("purpose") for i in icons}
        assert "any" in purposes and "maskable" in purposes, name
        for icon in icons:
            rel = icon["src"].removeprefix("/static/")
            assert (settings.BASE_DIR / "static" / rel).exists(), icon["src"]


def test_pwa_icons_actually_carry_the_logo():
    """Guards the regression these icons were built to fix: the originals were
    flat single-colour squares, so installed apps showed a blank tile. A rendered
    logo has many distinct colours; a flat placeholder has one."""
    from django.conf import settings
    from PIL import Image

    pwa = settings.BASE_DIR / "static" / "pwa"
    names = ["icon-192.png", "icon-512.png", "icon-180.png",
             "icon-maskable-192.png", "icon-maskable-512.png"]
    names += [n.replace("icon-", "icon-ops-") for n in names]
    for name in names:
        path = pwa / name
        assert path.exists(), name
        with Image.open(path) as im:
            assert im.width == im.height, f"{name} must be square, got {im.size}"
            assert len(im.convert("RGB").getcolors(maxcolors=100_000) or []) > 500, (
                f"{name} looks like a flat placeholder, not the Gaamos logo"
            )


def test_ops_icons_are_black_backed():
    """Ops ships a black-background variant. Corners are pure black, and the
    frame is dark overall — a regression to the light set would fail both."""
    from django.conf import settings
    from PIL import Image

    pwa = settings.BASE_DIR / "static" / "pwa"
    for name in ("icon-ops-192.png", "icon-ops-512.png", "icon-ops-180.png",
                 "icon-ops-maskable-192.png", "icon-ops-maskable-512.png"):
        with Image.open(pwa / name) as im:
            rgb = im.convert("RGB")
            w, h = rgb.size
            for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
                assert rgb.getpixel(corner) == (0, 0, 0), f"{name} corner {corner} not black"
            pixels = list(rgb.getdata())
            mean = sum(sum(p) / 3 for p in pixels) / len(pixels)
            assert mean < 60, f"{name} mean luminance {mean:.1f} — background not black"


@pytest.mark.django_db
def test_offline_page_on_apex(client):
    resp = client.get("/offline/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "offline" in body.lower()
    assert "Gaamos" in body
    # standalone: no external assets — the SW must be able to serve this with zero network
    assert "fonts.googleapis.com" not in body
    assert "app.css" not in body


@pytest.mark.django_db
def test_sw_behaviour_markers(client):
    """The rewritten SW: versioned cache, /offline/ precached, network-first
    navigations, and no naive cache-everything fallback to '/'.

    The VERSION literal is deliberately not pinned — the SW's own convention is
    to bump it whenever precached asset content changes, so pinning it here
    would fail the suite on every legitimate bump.
    """
    import re

    body = client.get("/sw.js").content.decode()
    assert re.search(r'VERSION = "v\d+"', body)
    assert '"/offline/"' in body
    assert "navigate" in body                 # navigation branch exists
    assert 'c.addAll(["/"])' not in body      # old stub's cache-of-'/' is gone
    assert "ignoreSearch" in body             # static matching tolerates ?v= busters
