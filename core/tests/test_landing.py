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
    assert "yourhotel." in body  # branch domain built from base_domain


@pytest.mark.django_db
def test_landing_pricing_and_footer(client):
    body = client.get("/en/").content.decode()
    assert "Simple pricing that grows with you" in body
    assert "Business" in body and "VIP" in body
    assert "Rs 4,000" in body and "Rs 5,500" in body   # monthly
    assert "Rs 3,200" in body and "Rs 4,400" in body   # annual, −20%
    assert "Rs 3,000" not in body and "Rs 7,000" not in body  # superseded prices
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


@pytest.mark.django_db
def test_pricing_offers_a_monthly_annual_toggle(client):
    """Both prices ship in the markup and Alpine swaps them, so the page needs
    no request to change billing period."""
    body = client.get("/en/").content.decode()
    assert 'x-data="{ annual: true }"' in body
    assert 'aria-label="Billing period"' in body
    assert ">Monthly<" in body
    assert "Annual" in body and "20%" in body


@pytest.mark.django_db
def test_the_annual_discount_is_exactly_twenty_percent(client):
    """The discount is advertised as −20%; if a price is ever edited without
    its partner, this is what catches it. Parsed from the rendered page rather
    than from the constants, so the guest sees what the test checks."""
    import re
    body = client.get("/en/").content.decode()
    # Scoped to the section: the hero's mock order queue also prints "Rs 40"
    # and friends, and a page-wide match silently picks those up too.
    section = body[body.index('id="pricing"'):]
    section = section[:section.index("</section>")]
    prices = [int(m.replace(",", ""))
              for m in re.findall(r"Rs ([\d,]+)</span>", section)]
    assert len(prices) == 4, f"expected 4 rendered prices, got {prices}"
    annual_business, monthly_business, annual_vip, monthly_vip = prices
    assert monthly_business == 4000 and annual_business == 3200
    assert monthly_vip == 5500 and annual_vip == 4400
    for monthly, annual in ((monthly_business, annual_business),
                            (monthly_vip, annual_vip)):
        assert annual == round(monthly * 0.8), f"{annual} is not 20% off {monthly}"


@pytest.mark.django_db
def test_a_no_js_visitor_still_sees_a_price(client):
    """x-show hides the monthly span via [x-cloak] until Alpine runs, so the
    annual price must be the one rendered without a cloak — an empty price is
    worse than a price that needs a click to change."""
    body = client.get("/en/").content.decode()
    section = body[body.index('id="pricing"'):]
    section = section[:section.index("</section>")]
    assert 'x-show="annual">Rs 3,200' in section
    assert 'x-show="!annual" x-cloak>Rs 4,000' in section
