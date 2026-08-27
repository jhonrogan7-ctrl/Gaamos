from datetime import timedelta

from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import SimpleTestCase
from django.utils import timezone

from menu.models import Branch, Company, Order, OrderItem, GuestSession, Table
from menu.dashboard.views import _table_card_groups
from menu.tenancy import set_current_company, reset_current_company
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
        self.g1 = GuestSession.objects.create(branch=self.branch, table=self.t4,
                                              token="c-g1", label="Guest A", name="Bikash",
                                              contact="+977 9812 34567")
        g2 = GuestSession.objects.create(branch=self.branch, table=self.t4,
                                         token="c-g2", label="Guest B", name="Sita")
        self.o1 = Order.objects.create(branch=self.branch, table=self.t4, guest_session=self.g1,
                                       status=Order.STATUS_NEW)
        OrderItem.objects.create(order=self.o1, name="Coffee", unit_price=100, qty=1)
        self.o2 = Order.objects.create(branch=self.branch, table=self.t4, guest_session=g2,
                                       status=Order.STATUS_SERVED)
        OrderItem.objects.create(order=self.o2, name="Tea", unit_price=50, qty=1)

    def test_card_has_status_counts_names_and_timing(self):
        cards, _ = _table_card_groups([self.branch])
        card = cards[0]
        self.assertEqual(card["new_count"], 1)
        self.assertEqual(card["served_count"], 1)
        self.assertEqual(card["guest_names"], ["Bikash", "Sita"])
        self.assertEqual(card["lead_contact"], "+977 9812 34567")
        self.assertEqual(card["opened_at"], self.g1.created_at)
        self.assertEqual(card["last_order_at"], max(self.o1.created_at, self.o2.created_at))

    def test_lead_contact_is_the_lead_guests_own_contact(self):
        # Lead guest (oldest session) has no contact, a later guest does:
        # the card must NOT borrow the later guest's phone.
        GuestSession.objects.filter(token="c-g1").update(contact="")
        GuestSession.objects.filter(token="c-g2").update(contact="+977 9843 55678")
        cards, _ = _table_card_groups([self.branch])
        self.assertEqual(cards[0]["lead_contact"], "")


class TableFilterParsingTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        U = get_user_model()
        self.owner = U.objects.create_user("boss3", password="pass")
        self.make_owner(self.owner)
        self.branch = Branch.objects.create(company=self.company, name="Lake", slug="lake")
        self.t4 = Table.objects.create(branch=self.branch, label="4")
        self.t7 = Table.objects.create(branch=self.branch, label="7")
        g4 = GuestSession.objects.create(branch=self.branch, table=self.t4, token="f-g4", label="Guest A")
        # t7 also gets an open session so an unfiltered ?group=table really would
        # render a "Table 7" card — that is what makes the filter test discriminate.
        g7 = GuestSession.objects.create(branch=self.branch, table=self.t7, token="f-g7", label="Guest A")
        gT = GuestSession.objects.create(branch=self.branch, table=None, token="f-gt", label="Guest A")
        self.o4 = Order.objects.create(branch=self.branch, table=self.t4, guest_session=g4, table_label="4")
        OrderItem.objects.create(order=self.o4, name="Coffee", unit_price=100, qty=1)
        self.o7 = Order.objects.create(branch=self.branch, table=self.t7, guest_session=g7, table_label="7")
        OrderItem.objects.create(order=self.o7, name="Tea", unit_price=50, qty=1)
        self.oT = Order.objects.create(branch=self.branch, table=None, guest_session=gT, table_label="")
        OrderItem.objects.create(order=self.oT, name="Juice", unit_price=150, qty=1)
        self.login_as(self.owner)

    def test_flat_filtered_to_one_table(self):
        resp = self.client.get(f"/dashboard/orders/?tables={self.t4.pk}")
        # ``#{o4.number}`` == ``#1`` is a substring of chrome (``#15171d`` theme
        # colour in base.html), so the positive check reads the order set.
        self.assertIn(self.o4.number, {o.number for o in resp.context["orders"]})
        body = resp.content.decode()
        self.assertNotIn(f"#{self.o7.number}", body)
        self.assertNotIn(f"#{self.oT.number}", body)

    def test_takeaway_token_includes_only_tableless_orders(self):
        # ``#{o4.number}`` == ``#1`` collides with chrome (``#15171d`` theme
        # colour, ``?v=178…`` asset stamp), so assert on the rendered order set.
        nums = {o.number for o in
                self.client.get("/dashboard/orders/?tables=takeaway").context["orders"]}
        self.assertIn(self.oT.number, nums)
        self.assertNotIn(self.o4.number, nums)

    def test_table_and_takeaway_compose(self):
        resp = self.client.get(f"/dashboard/orders/?tables={self.t4.pk},takeaway")
        nums = {o.number for o in resp.context["orders"]}
        self.assertIn(self.o4.number, nums)
        self.assertIn(self.oT.number, nums)
        self.assertNotIn(f"#{self.o7.number}", resp.content.decode())

    def test_junk_tokens_ignored_and_empty_is_unfiltered(self):
        nums = {o.number for o in
                self.client.get("/dashboard/orders/?tables=abc,").context["orders"]}
        self.assertIn(self.o4.number, nums)
        self.assertIn(self.o7.number, nums)

    def test_status_and_table_filter_compose(self):
        self.o4.status = Order.STATUS_SERVED
        self.o4.save()
        nums = {o.number for o in self.client.get(
            f"/dashboard/orders/?tables={self.t4.pk}&status=new").context["orders"]}
        self.assertNotIn(self.o4.number, nums)

    def test_group_table_unfiltered_shows_every_open_table(self):
        body = self.client.get("/dashboard/orders/?group=table").content.decode()
        self.assertIn("Table 4", body)
        self.assertIn("Table 7", body)

    def test_group_table_respects_table_filter(self):
        body = self.client.get(
            f"/dashboard/orders/?group=table&tables={self.t4.pk}").content.decode()
        self.assertIn("Table 4", body)
        self.assertNotIn("Table 7", body)

    def test_table_option_toggle_urls_add_and_remove(self):
        # No filter yet: each option's toggle URL ADDS its own table.
        opts0 = {o["table"].pk: o for o in
                 self.client.get("/dashboard/orders/").context["table_filter_options"]}
        self.assertFalse(opts0[self.t4.pk]["selected"])
        self.assertEqual(opts0[self.t4.pk]["toggle_url"],
                         f"/dashboard/orders/?tables={self.t4.pk}")
        # With t4 selected, t4's own row toggles OFF (back to a bare path) and
        # t7's row toggles to the combined "4,7" list.
        resp = self.client.get(f"/dashboard/orders/?tables={self.t4.pk}")
        opts = {o["table"].pk: o for o in resp.context["table_filter_options"]}
        self.assertTrue(opts[self.t4.pk]["selected"])
        self.assertEqual(opts[self.t4.pk]["toggle_url"], "/dashboard/orders/")
        self.assertFalse(opts[self.t7.pk]["selected"])
        self.assertEqual(
            opts[self.t7.pk]["toggle_url"],
            f"/dashboard/orders/?tables={self.t4.pk},{self.t7.pk}")
        self.assertEqual(
            resp.context["takeaway_toggle_url"],
            f"/dashboard/orders/?tables={self.t4.pk},takeaway")

    def test_toggle_urls_preserve_other_query_params(self):
        resp = self.client.get("/dashboard/orders/?group=table&status=new")
        opts = {o["table"].pk: o for o in resp.context["table_filter_options"]}
        url = opts[self.t4.pk]["toggle_url"]
        self.assertIn("group=table", url)
        self.assertIn("status=new", url)
        self.assertIn(f"tables={self.t4.pk}", url)
        tk = resp.context["takeaway_toggle_url"]
        self.assertIn("group=table", tk)
        self.assertIn("status=new", tk)
        self.assertIn("tables=takeaway", tk)

    def test_hostile_table_tokens_are_ignored_not_500(self):
        all_nums = {self.o4.number, self.o7.number, self.oT.number}
        # superscript two: str.isdigit() is True but int('²') raises ValueError
        r1 = self.client.get("/dashboard/orders/?tables=²")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual({o.number for o in r1.context["orders"]}, all_nums)
        # 20-digit token: parses to a Python int Postgres would reject
        r2 = self.client.get("/dashboard/orders/?tables=99999999999999999999")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual({o.number for o in r2.context["orders"]}, all_nums)

    def test_mixed_valid_and_hostile_tokens_filter_to_valid(self):
        r = self.client.get(
            f"/dashboard/orders/?tables={self.t4.pk},²,abc")
        self.assertEqual(r.status_code, 200)
        self.assertEqual({o.number for o in r.context["orders"]}, {self.o4.number})


class TableGroupsPartialTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        U = get_user_model()
        self.owner = U.objects.create_user("boss4", password="pass")
        self.make_owner(self.owner)
        self.branch = Branch.objects.create(company=self.company, name="Lake", slug="lake")
        self.t4 = Table.objects.create(branch=self.branch, label="4")
        g = GuestSession.objects.create(branch=self.branch, table=self.t4, token="p-g4", label="Guest A")
        o = Order.objects.create(branch=self.branch, table=self.t4, guest_session=g)
        OrderItem.objects.create(order=o, name="Coffee", unit_price=100, qty=1)
        self.login_as(self.owner)

    def test_partial_renders_only_the_cards_fragment(self):
        r = self.client.get("/dashboard/orders/table-groups/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("Table 4", body)
        self.assertNotIn("<aside class=\"side\"", body)  # no full page chrome

    def test_partial_honours_table_filter(self):
        t9 = Table.objects.create(branch=self.branch, label="9")
        GuestSession.objects.create(branch=self.branch, table=t9, token="p-g9", label="Guest A")
        body = self.client.get(
            f"/dashboard/orders/table-groups/?tables={self.t4.pk}").content.decode()
        self.assertIn("Table 4", body)
        self.assertNotIn("Table 9", body)

    def test_partial_requires_membership(self):
        self.client.logout()
        r = self.client.get("/dashboard/orders/table-groups/")
        self.assertIn(r.status_code, (302, 403))

    def test_branch_partial_404_for_other_company_branch(self):
        """Tenant scoping: branch from a different company is hidden as 404."""
        other = Company.objects.create(name='Other', slug='other')
        tok = set_current_company(other)
        try:
            fbranch = Branch.objects.create(company=other, name='Far', slug='far')
        finally:
            reset_current_company(tok)
        r = self.client.get(f'/dashboard/branch/{fbranch.slug}/orders/table-groups/')
        self.assertEqual(r.status_code, 404)

    def test_branch_partial_allowed_for_owner(self):
        """Owner can access their own branch's table-groups partial."""
        r = self.client.get(f'/dashboard/branch/{self.branch.slug}/orders/table-groups/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("Table 4", body)
        self.assertNotIn("<aside class=\"side\"", body)  # fragment, not full page

    def test_branch_partial_forbidden_for_unassigned_manager(self):
        """Intra-company branch-scoped manager must not access unassigned branches."""
        U = get_user_model()
        branch_a = Branch.objects.create(company=self.company, name="A", slug="a")
        branch_b = Branch.objects.create(company=self.company, name="B", slug="b")
        manager = U.objects.create_user("mgr", password="pass")
        self.make_manager(manager, branches=[branch_a])
        self.client.logout()
        self.login_as(manager)
        r = self.client.get(f'/dashboard/branch/{branch_b.slug}/orders/table-groups/')
        self.assertEqual(r.status_code, 403)
