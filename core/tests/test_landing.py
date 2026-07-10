import pytest


@pytest.mark.django_db
def test_landing_renders_on_apex(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Turn every table into" in body       # hero H1
    assert "point of sale" in body
    assert 'href="#contact"' in body             # nav + CTA target
    assert "QR menus · live orders · no app required" in body


@pytest.mark.django_db
def test_landing_features_section(client):
    body = client.get("/").content.decode()
    assert "Everything a busy venue needs" in body
    assert "Menu Builder" in body
    assert "Branded Menu" in body
    assert "Live Orders" in body
    assert "QR Codes" in body
    assert "Build your menu in minutes" in body


@pytest.mark.django_db
def test_landing_how_and_multibranch(client):
    body = client.get("/").content.decode()
    assert "Live by lunchtime" in body
    assert "Print your QRs" in body
    assert "Every location. One dashboard." in body
    assert "theterrace." in body  # branch domain built from base_domain
