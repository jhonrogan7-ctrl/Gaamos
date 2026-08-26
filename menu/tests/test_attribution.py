import pytest
from menu.models import Company, Branch, GuestSession, Order
from menu.tenancy import set_current_company


@pytest.mark.django_db
def test_order_guest_session_attribution():
    """Test that an Order can be attributed to a GuestSession via related_name."""
    co = Company.objects.create(name="Cafe", slug="cafe")
    set_current_company(co)
    br = Branch.objects.create(company=co, name="Main", address="x")
    gs = GuestSession.objects.create(branch=br, token="t0001", label="Guest A")

    # Create an order with a guest session
    order = Order.objects.create(company=co, branch=br, guest_session=gs)

    # Test the reverse relation
    assert gs.orders.count() == 1
    assert gs.orders.first() == order


@pytest.mark.django_db
def test_order_without_guest_session():
    """Test that an Order can still allow guest_session to be None."""
    co = Company.objects.create(name="Cafe", slug="cafe")
    set_current_company(co)
    br = Branch.objects.create(company=co, name="Main", address="x")

    # Create an order without a guest session
    order = Order.objects.create(company=co, branch=br)

    # Test that guest_session can be None
    assert order.guest_session is None
