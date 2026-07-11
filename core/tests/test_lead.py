import pytest

from core.models import Lead


@pytest.mark.django_db
def test_lead_creation_and_str():
    lead = Lead.objects.create(
        name="Aashish Sharma",
        venue_name="Chill Zone Café",
        phone="+977 9812345678",
        venue_type="Café",
    )
    assert lead.email == ""
    assert lead.message == ""
    assert lead.created_at is not None
    assert str(lead) == "Chill Zone Café — Aashish Sharma"


@pytest.mark.django_db
def test_lead_venue_type_choices():
    labels = [c[0] for c in Lead.VENUE_TYPES]
    assert labels == ["Café", "Restaurant", "Bar", "Other"]
