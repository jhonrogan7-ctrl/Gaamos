from datetime import timedelta

from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import SimpleTestCase
from django.utils import timezone

from menu.models import Branch, Order, OrderItem, GuestSession, Table
from menu.dashboard.views import _table_card_groups
from menu.tests.base import TenantTestCase


def _render(dt):
    t = Template("{% load order_extras %}{{ dt|smart_datetime }}")
    return t.render(Context({"dt": dt}))


class SmartDatetimeTest(SimpleTestCase):
    def test_today_shows_today_and_clock(self):
        now = timezone.localtime()
        self.assertEqual(_render(now), f"Today · {now:%H:%M}")

    def test_yesterday_shows_yesterday(self):
        dt = timezone.localtime() - timedelta(days=1)
        self.assertEqual(_render(dt), f"Yesterday · {dt:%H:%M}")

    def test_older_shows_day_and_month(self):
        dt = timezone.localtime() - timedelta(days=6)
        self.assertEqual(_render(dt), f"{dt.day} {dt:%b} · {dt:%H:%M}")

    def test_none_is_blank(self):
        self.assertEqual(_render(None), "")


class TableCardAnnotationsTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(company=self.company, name="Lake", slug="lake")
        self.t4 = Table.objects.create(branch=self.branch, label="4")
        g1 = GuestSession.objects.create(branch=self.branch, table=self.t4,
                                         token="c-g1", label="Guest A", name="Bikash",
                                         contact="+977 9812 34567")
        g2 = GuestSession.objects.create(branch=self.branch, table=self.t4,
                                         token="c-g2", label="Guest B", name="Sita")
        o1 = Order.objects.create(branch=self.branch, table=self.t4, guest_session=g1,
                                  status=Order.STATUS_NEW)
        OrderItem.objects.create(order=o1, name="Coffee", unit_price=100, qty=1)
        o2 = Order.objects.create(branch=self.branch, table=self.t4, guest_session=g2,
                                  status=Order.STATUS_SERVED)
        OrderItem.objects.create(order=o2, name="Tea", unit_price=50, qty=1)

    def test_card_has_status_counts_names_and_timing(self):
        cards, _ = _table_card_groups([self.branch])
        card = cards[0]
        self.assertEqual(card["new_count"], 1)
        self.assertEqual(card["served_count"], 1)
        self.assertEqual(card["guest_names"], ["Bikash", "Sita"])
        self.assertEqual(card["lead_contact"], "+977 9812 34567")
        self.assertIsNotNone(card["opened_at"])
        self.assertIsNotNone(card["last_order_at"])

    def test_lead_contact_falls_through_to_first_session_with_a_contact(self):
        # first session (oldest) has no contact -> lead_contact takes the next one
        GuestSession.objects.filter(token="c-g1").update(contact="")
        cards, _ = _table_card_groups([self.branch])
        self.assertEqual(cards[0]["lead_contact"], "")  # Sita has none either
