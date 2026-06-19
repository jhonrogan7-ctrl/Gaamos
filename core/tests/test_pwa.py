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
