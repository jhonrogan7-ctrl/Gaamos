import pytest


@pytest.mark.django_db
def test_base_links_manifest_and_registers_sw(client):
    body = client.get("/").content.decode()
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
    body = client.get("/").content.decode()
    assert "apple-touch-icon" in body
    assert "apple-mobile-web-app-capable" in body


def test_manifests_have_distinct_ids():
    import json
    from django.conf import settings
    pwa = settings.BASE_DIR / "static" / "pwa"
    guest = json.loads((pwa / "manifest.webmanifest").read_text())
    dash = json.loads((pwa / "manifest-dashboard.webmanifest").read_text())
    assert guest["id"] == "/" and guest["start_url"] == "/"
    assert dash["id"] == "/dashboard/" and dash["start_url"] == "/dashboard/"
    assert guest["name"] == "Gaamos Menu" and dash["name"] == "Gaamos Dashboard"
    assert {i["src"] for i in guest["icons"]} == {i["src"] for i in dash["icons"]}


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
