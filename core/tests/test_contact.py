import pytest

from core.models import Lead


@pytest.mark.django_db
def test_contact_valid_post_creates_lead_and_returns_success(client):
    resp = client.post(
        "/en/contact",
        {
            "name": "Aashish Sharma",
            "venue_name": "Chill Zone Café",
            "phone": "+977 9812345678",
            "email": "hi@chillzone.test",
            "venue_type": "Café",
            "message": "2 branches, ~60 items",
        },
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    assert Lead.objects.count() == 1
    lead = Lead.objects.get()
    assert lead.venue_name == "Chill Zone Café"
    assert "Request received" in resp.content.decode()


@pytest.mark.django_db
def test_contact_missing_phone_is_rejected(client):
    resp = client.post(
        "/en/contact",
        {"name": "Aashish Sharma", "venue_name": "Chill Zone Café", "phone": ""},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    assert Lead.objects.count() == 0
    body = resp.content.decode()
    assert "name, venue name and phone" in body
    assert "Aashish Sharma" in body  # submitted values preserved


@pytest.mark.django_db
def test_contact_venue_type_whitelisted(client):
    client.post("/en/contact", {
        "name": "A", "venue_name": "B", "phone": "+977 98",
        "venue_type": "<script>evil</script>",
    }, HTTP_HX_REQUEST="true")
    lead = Lead.objects.get()
    assert lead.venue_type == "Café"  # non-whitelisted coerced


@pytest.mark.django_db
def test_contact_xss_venue_type_not_reflected(client):
    payload = "'-alert(document.domain)-'"
    resp = client.post("/en/contact", {
        "name": "A", "venue_name": "B", "phone": "",  # error path
        "venue_type": payload,
    }, HTTP_HX_REQUEST="true")
    assert Lead.objects.count() == 0
    assert payload not in resp.content.decode()  # coerced to Café, not echoed


@pytest.mark.django_db
def test_contact_non_htmx_post_renders_full_page(client):
    resp = client.post("/en/contact", {
        "name": "Aashish", "venue_name": "Chill Zone", "phone": "+977 98",
    })  # no HX-Request header
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Turn every table into" in body      # full landing page
    assert "Request received" in body           # success state inline
    assert Lead.objects.count() == 1


@pytest.mark.django_db
def test_contact_non_htmx_get_redirects(client):
    resp = client.get("/en/contact")  # no HX-Request header
    assert resp.status_code == 302
    assert resp["Location"] == "/en/#contact"


@pytest.mark.django_db
def test_contact_htmx_post_still_returns_fragment(client):
    resp = client.post("/en/contact", {
        "name": "Aashish", "venue_name": "Chill Zone", "phone": "+977 98",
    }, HTTP_HX_REQUEST="true")
    body = resp.content.decode()
    assert "Request received" in body
    assert "Turn every table into" not in body  # fragment, not full page
