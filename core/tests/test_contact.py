import pytest

from core.models import Lead


@pytest.mark.django_db
def test_contact_valid_post_creates_lead_and_returns_success(client):
    resp = client.post(
        "/contact",
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
        "/contact",
        {"name": "Aashish Sharma", "venue_name": "Chill Zone Café", "phone": ""},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    assert Lead.objects.count() == 0
    body = resp.content.decode()
    assert "name, venue name and phone" in body
    assert "Aashish Sharma" in body  # submitted values preserved
