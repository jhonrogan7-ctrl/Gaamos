import pytest


@pytest.mark.django_db
def test_landing_renders_on_en_prefix(client):
    resp = client.get("/en/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Turn every table into" in body       # hero H1
    assert "point of sale" in body
    assert 'href="#contact"' in body             # nav + CTA target
    assert "QR menus · live orders · no app required" in body


@pytest.mark.django_db
def test_landing_features_section(client):
    body = client.get("/en/").content.decode()
    assert "Everything a busy venue needs" in body
    assert "Menu Builder" in body
    assert "Branded Menu" in body
    assert "Live Orders" in body
    assert "QR Codes" in body
    assert "Build your menu in minutes" in body


@pytest.mark.django_db
def test_landing_how_and_multibranch(client):
    body = client.get("/en/").content.decode()
    assert "Live by lunchtime" in body
    assert "Print your QRs" in body
    assert "Every location. One dashboard." in body
    assert "theterrace." in body  # branch domain built from base_domain


@pytest.mark.django_db
def test_landing_pricing_and_footer(client):
    body = client.get("/en/").content.decode()
    assert "Simple pricing that grows with you" in body
    assert "Business" in body and "VIP" in body
    assert "Rs 3,000" in body and "Rs 7,000" in body
    assert "Starter" not in body and "$29" not in body   # old placeholders gone
    assert "Most popular" in body            # Business is highlighted
    assert "Everything in Business" in body  # VIP card content
    assert "© 2026 Gaamos" in body


@pytest.mark.django_db
def test_landing_logo_and_hero_assets(client):
    body = client.get("/en/").content.decode()
    assert "images/gaamos-logo.png" in body           # real logo in nav + footer
    assert "images/landing/menu-screen.jpg" in body   # menu screenshot hero
    assert "images/landing/demo-qr.png" in body       # scannable demo QR
    assert "Scan to try the live demo" in body
    assert "images/landing/order-screen.jpg" not in body  # order screen dropped from hero
    assert "Start free" not in body                   # no free tier anywhere


@pytest.mark.django_db
def test_landing_contact_section(client):
    body = client.get("/en/").content.decode()
    assert "Tell us about your venue" in body
    assert 'hx-post="/en/contact"' in body
    assert 'id="contact"' in body
    assert "Restaurant" in body and "Bar" in body  # venue-type chips
