import pytest
from django.test import RequestFactory
from django.http import HttpResponse
from menu.models import Company, Branch, Table, GuestSession
from menu.tenancy import set_current_company
from menu.guest_sessions import get_or_create_session, attach_cookie


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


@pytest.mark.django_db
def test_get_or_create_session_no_cookie():
    """First call with no cookie creates 'Guest A' session."""
    co = Company.objects.create(name="Cafe", slug="cafe")
    set_current_company(co)
    br = Branch.objects.create(company=co, name="Main", address="x")
    table = Table.objects.create(company=co, branch=br, label="Table 1")

    factory = RequestFactory()
    request = factory.get('/')

    gs, token, created = get_or_create_session(request, br, table)

    assert created is True
    assert gs.label == "Guest A"
    assert gs.branch_id == br.id
    assert gs.table_id == table.id
    assert gs.token == token
    assert len(token) > 0


@pytest.mark.django_db
def test_get_or_create_session_second_guest():
    """Second call on same table creates 'Guest B'."""
    co = Company.objects.create(name="Cafe", slug="cafe")
    set_current_company(co)
    br = Branch.objects.create(company=co, name="Main", address="x")
    table = Table.objects.create(company=co, branch=br, label="Table 1")

    factory = RequestFactory()

    # First guest
    request1 = factory.get('/')
    gs1, token1, created1 = get_or_create_session(request1, br, table)
    assert created1 is True
    assert gs1.label == "Guest A"

    # Second guest (new browser/token)
    request2 = factory.get('/')
    gs2, token2, created2 = get_or_create_session(request2, br, table)
    assert created2 is True
    assert gs2.label == "Guest B"
    assert token1 != token2


@pytest.mark.django_db
def test_get_or_create_session_existing_token():
    """Existing valid token returns same session (created=False)."""
    co = Company.objects.create(name="Cafe", slug="cafe")
    set_current_company(co)
    br = Branch.objects.create(company=co, name="Main", address="x")
    table = Table.objects.create(company=co, branch=br, label="Table 1")

    factory = RequestFactory()

    # First call: create guest session
    request1 = factory.get('/')
    gs1, token1, created1 = get_or_create_session(request1, br, table)
    assert created1 is True

    # Second call: present the same token in cookies
    request2 = factory.get('/')
    request2.COOKIES = {f'gaamos_gs': token1}
    gs2, token2, created2 = get_or_create_session(request2, br, table)

    assert created2 is False
    assert gs2.id == gs1.id
    assert token2 == token1


@pytest.mark.django_db
def test_attach_cookie():
    """attach_cookie sets the cookie on response."""
    from menu.guest_sessions import COOKIE

    response = HttpResponse()
    token = "test_token_12345"

    result = attach_cookie(response, token)

    assert result is response
    assert COOKIE in response.cookies
    assert response.cookies[COOKIE]['httponly'] is True
    assert response.cookies[COOKIE]['samesite'] == 'Lax'


@pytest.mark.django_db
def test_company_identity_mode_defaults():
    """A new Company defaults to identity_mode='auto' and identity_skippable=True."""
    co = Company.objects.create(name="Test Venue", slug="test-venue")
    assert co.identity_mode == 'auto'
    assert co.identity_skippable is True
