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
