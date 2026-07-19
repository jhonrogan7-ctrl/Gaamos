import pytest

from core.models import Lead


@pytest.mark.django_db
def test_lead_creation_and_str():
    lead = Lead.objects.create(
        name="Suman Thapa",
        venue_name="Momo Ghar Café",
        phone="+977 9812345678",
        venue_type="Café",
    )
    assert lead.email == ""
    assert lead.message == ""
    assert lead.created_at is not None
    assert str(lead) == "Momo Ghar Café — Suman Thapa"


@pytest.mark.django_db
def test_lead_venue_type_choices():
    labels = [c[0] for c in Lead.VENUE_TYPES]
    assert labels == ["Café", "Restaurant", "Bar", "Hotel", "Other"]


@pytest.mark.django_db
def test_lead_defaults_new_status_no_company():
    lead = Lead.objects.create(name="A", venue_name="V", phone="98")
    assert lead.status == "new"
    assert lead.company is None
