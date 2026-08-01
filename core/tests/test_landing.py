import re
from pathlib import Path

import pytest

from django.conf import settings


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
    assert "Live Orders" in body
    assert "QR Codes" in body
    assert "Build your menu in minutes" in body


@pytest.mark.django_db
def test_landing_how_and_multibranch(client):
    body = client.get("/en/").content.decode()
    assert "Live by lunchtime" in body
    assert "Print your QRs" in body
    # multi-branch is now the closing panel of "how it works", not its own section
    assert "Every location. One dashboard." in body
    assert "extra logins" in body


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


CLIENTS = [
    "Pokhara Metro Eco Hotel",
    "Chill Zone Restaurant &amp; Bar",   # escaped by the template
    "Kailash Prabat Cafe",
    "The Tranquility Inn",
    "The Juicery Cafe",
]


def _card(body, plan_name):
    """The markup of one pricing card, so a feature bullet can't pass a test by
    appearing on the other plan."""
    cards = body[body.index('class="orn-plans"'):]
    start = cards.index(f">{plan_name}</div>")
    nxt = cards.find('class="orn-plan ', start)
    return cards[start:nxt if nxt != -1 else cards.index("</section>")]


@pytest.mark.django_db
def test_each_tier_states_its_table_limit(client):
    """Tables are the one limit that differs between the plans, so each card has
    to say its own number — 25 for Business, none for VIP."""
    body = client.get("/en/").content.decode()
    business, vip = _card(body, "Business"), _card(body, "VIP")
    assert "Up to 25 tables" in business
    assert "Unlimited tables" not in business
    assert "Unlimited tables" in vip
    assert "Up to 25 tables" not in vip


@pytest.mark.django_db
def test_landing_names_every_client(client):
    body = client.get("/en/").content.decode()
    section = body[body.index('id="clients"'):]
    section = section[:section.index("</section>")]
    for name in CLIENTS:
        assert name in section, f"{name} missing from the clients section"


@pytest.mark.django_db
def test_clients_sit_between_how_it_works_and_pricing(client):
    """Proof that other venues run this lands right before the price. Measured on
    the rendered page rather than on home.html's include order."""
    body = client.get("/en/").content.decode()
    assert body.index('id="how"') < body.index('id="clients"') < body.index('id="pricing"')


@pytest.mark.django_db
def test_the_hero_strip_no_longer_names_a_single_client(client):
    """One name in the strip read as arbitrary once all five were listed below."""
    body = client.get("/en/").content.decode()
    hero = body[body.index('id="top"'):]
    hero = hero[:hero.index("</section>")]
    assert "Juicery" not in hero
    assert "across the region" in hero   # the strip itself stays


@pytest.mark.django_db
def test_client_names_are_not_translated(client):
    """Venue names are proper nouns — they render as literals in every locale,
    the same rule the mock menu and order data follow."""
    for url in ("/ne/", "/ka/"):
        body = client.get(url).content.decode()
        for name in CLIENTS:
            assert name in body, f"{name} missing from {url}"


@pytest.mark.django_db
def test_landing_logo_and_hero_assets(client):
    body = client.get("/en/").content.decode()
    assert "images/gaamos-logo.png" in body           # real logo in nav + footer
    assert "images/landing/demo-qr.png" in body       # scannable demo QR
    assert "Scan to try the live demo" in body
    assert "images/landing/table-qrs/qr-1.png" in body  # real generated table codes
    # the hero menu is drawn in markup now — no screenshot of it anywhere
    assert "images/landing/menu-screen.jpg" not in body
    assert "images/landing/order-screen.jpg" not in body
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
def test_billing_switcher_halves_are_toggled_by_alpine_only(client):
    """The active half is `.is-on`. Annual carries it statically so a no-JS
    visitor sees the state its price matches; Alpine's object syntax is what
    removes it again on click — a string :class would leave the static one
    behind and light both halves at once."""
    body = client.get("/en/").content.decode()
    switch = body[body.index('class="orn-switch"'):]
    switch = switch[:switch.index("</div>")]
    assert """:class="{ 'is-on': !annual }\"""" in switch      # Monthly: bound only
    assert """class="is-on" :class="{ 'is-on': annual }\"""" in switch  # Annual: static + bound


@pytest.mark.django_db
def test_the_annual_discount_is_exactly_twenty_percent(client):
    """The discount is advertised as −20%; if a price is ever edited without
    its partner, this is what catches it. Parsed from the rendered page rather
    than from the constants, so the guest sees what the test checks."""
    body = client.get("/en/").content.decode()
    # Scoped to the section: the hero's mock menu also prints "Rs 40"
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


# ── printed-ornament design ────────────────────────────────────────────

@pytest.mark.django_db
def test_landing_loads_its_own_stylesheet_and_fonts(client):
    body = client.get("/en/").content.decode()
    assert "css/landing.css" in body
    for family in ("Marcellus", "Karla", "JetBrains+Mono"):
        assert family in body


@pytest.mark.django_db
def test_ornament_assets_are_masks_not_images(client):
    """The ornaments are recoloured by `currentColor` through a CSS mask, which
    is what lets one asset read ink-on-cream and cream-on-ink. Shipping one as
    an <img> would freeze it at the colour it was cut in."""
    body = client.get("/en/").content.decode()
    assert "images/ornament/" not in body
    css = (settings.BASE_DIR / "static" / "css" / "landing.css").read_text()
    for cut in ("orn-band-tile", "orn-medallion", "orn-corner",
                "orn-birds", "orn-figures", "orn-column", "orn-full"):
        asset = settings.BASE_DIR / "static" / "images" / "ornament" / f"{cut}.png"
        assert asset.exists(), f"missing ornament cut: {cut}"
        assert f"images/ornament/{cut}.png" in css


def test_landing_palette_stays_off_the_dashboard():
    """The landing runs the Madder Red palette; the dashboard and guest menu
    keep the house Saffron tokens. Scoping the palette to `.orn` instead of
    `:root` is the whole reason those two can differ."""
    css = (settings.BASE_DIR / "static" / "css" / "landing.css").read_text()
    assert re.search(r"^\s*:root\s*[,{]", css, re.M) is None, "landing.css defines :root tokens"
    palette = css[css.index(".orn {"):css.index("}")]
    assert "--ink: #8E2B23" in palette
    assert "--cream: #F8F1E6" in palette
    assert "--accent: #1F4E4A" in palette


def test_landing_css_mobile_overrides_come_last():
    """These media queries share specificity with the desktop rules above them,
    so source order is what decides. Anchor it: a later edit that appends a
    desktop rule under them would silently win at every width."""
    css = (settings.BASE_DIR / "static" / "css" / "landing.css").read_text()
    first_media = css.index("@media (max-width: 1024px)")
    assert css.index(".orn-footer-copy") < first_media
    tail = css[first_media:]
    assert re.search(r"\n\.orn[\w-]*\s*[,{]", tail) is None, \
        "a top-level .orn rule was added after the responsive block"


def test_no_multiline_django_comment_tags_in_templates():
    """`{# … #}` is matched by a non-DOTALL regex, so a comment that spans two
    lines is never a comment — it renders to the visitor as page text. This
    shipped once on the pricing cards; {% comment %} is the multi-line form."""
    offenders = []
    for path in Path(settings.BASE_DIR / "templates").rglob("*.html"):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if "{#" in line and "#}" not in line:
                offenders.append(f"{path.relative_to(settings.BASE_DIR)}:{n}")
    assert not offenders, f"multi-line {{# #}} renders as visible text: {offenders}"


@pytest.mark.django_db
def test_no_template_syntax_leaks_into_the_rendered_page(client):
    for url in ("/en/", "/ne/", "/ka/"):
        body = client.get(url).content.decode()
        for leak in ("{#", "#}", "{%", "{{"):
            assert leak not in body, f"{leak} leaked into {url}"
