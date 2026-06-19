import pytest

@pytest.mark.django_db
def test_base_links_manifest_and_registers_sw(client):
    body = client.get("/").content.decode()
    assert 'rel="manifest"' in body
    assert "manifest.webmanifest" in body
    assert "serviceWorker" in body  # registration script present
