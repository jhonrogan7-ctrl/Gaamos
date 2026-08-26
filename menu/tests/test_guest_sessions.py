import pytest
from menu.models import Company, Branch, GuestSession
from menu.tenancy import set_current_company


@pytest.mark.django_db
def test_guest_session_defaults():
    co = Company.objects.create(name="Cafe", slug="cafe")
    set_current_company(co)
    br = Branch.objects.create(company=co, name="Main", address="x")
    gs = GuestSession.objects.create(branch=br, token="t0001", label="Guest A")
    assert gs.company_id == co.id
    assert gs.verified is False
    assert gs.closed_at is None
    assert str(gs)  # __str__ does not raise
