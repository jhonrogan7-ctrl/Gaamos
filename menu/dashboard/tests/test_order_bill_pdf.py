"""Printable bill for a SINGLE order — Janak asked for this on the order
detail screen, for any kind of order, without touching the existing
table/takeaway split-or-combine bill (Task 3.4: _bill_context /
_bill_pdf_context / _bill_pdf_response / bill_summary_pdf.html).

Built purely from Order/OrderItem, same principle as order_detail itself:
no GuestSession or Table required, so it works for a table order, a
takeaway order, a walk-in with a session, and a walk-in / legacy order with
no session at all — the case the table-level bill can never reach.
"""
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string

from menu.models import Branch, Company, GuestSession, Order, OrderItem, Table
from menu.tenancy import reset_current_company, set_current_company
from menu.tests.base import TenantTestCase


class OrderBillPdfTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        U = get_user_model()
        self.owner = U.objects.create_user('pdfboss', password='pass')
        self.make_owner(self.owner)
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')
        self.table = Table.objects.create(branch=self.branch, label='7')
        self.order = Order.objects.create(branch=self.branch, table=self.table,
                                          table_label='7', total=300)
        OrderItem.objects.create(order=self.order, name='Latte', unit_price=150, qty=2)
        self.login_as(self.owner)

    def _get(self, order=None):
        return self.client.get(f'/dashboard/order/{(order or self.order).pk}/bill/print/')

    def test_returns_pdf(self):
        r = self._get()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))

    def test_works_for_takeaway_order(self):
        o = Order.objects.create(branch=self.branch, total=90)
        OrderItem.objects.create(order=o, name='Tea', unit_price=90, qty=1)
        r = self._get(o)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b'%PDF'))

    def test_works_for_order_with_guest_session(self):
        gs = GuestSession.objects.create(branch=self.branch, table=self.table,
                                         token='pdf-gs', label='Guest A', name='Bikash')
        o = Order.objects.create(branch=self.branch, table=self.table, guest_session=gs, total=90)
        r = self._get(o)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b'%PDF'))

    def test_works_for_order_with_no_guest_session_at_all(self):
        # self.order (setUp) has no guest_session — the walk-in/legacy case
        # the table-level split/combine bill can never reach.
        r = self._get()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b'%PDF'))

    def test_foreign_company_order_is_404(self):
        other = Company.objects.create(name='Other', slug='other')
        tok = set_current_company(other)
        try:
            fbranch = Branch.objects.create(company=other, name='Far', slug='far')
            forder = Order.objects.create(branch=fbranch, total=0)
        finally:
            reset_current_company(tok)
        r = self._get(forder)
        self.assertEqual(r.status_code, 404)

    def test_forbidden_for_unassigned_manager(self):
        branch_b = Branch.objects.create(company=self.company, name='B', slug='b')
        order_b = Order.objects.create(branch=branch_b, total=0)
        U = get_user_model()
        manager = U.objects.create_user('pdfmgr', password='pass')
        self.make_manager(manager, branches=[self.branch])
        self.client.logout()
        self.login_as(manager)
        r = self._get(order_b)
        self.assertEqual(r.status_code, 403)

    def test_does_not_mutate_anything(self):
        order_count_before = Order.objects.count()
        self._get()
        self.assertEqual(Order.objects.count(), order_count_before)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_NEW)

    def test_note_is_not_on_the_bill(self):
        # Janak's own confirmed decision (msg 538): a note is for staff, not
        # the bill. PDF bytes aren't reliably grep-able text, so assert at
        # the template-string level instead.
        OrderItem.objects.create(order=self.order, name='Momo', unit_price=180, qty=1,
                                 note='No chili please')
        html = render_to_string('dashboard/order_bill_pdf.html', {
            'order': self.order, 'branch': self.branch, 'venue_name': 'Test Co',
        })
        self.assertNotIn('No chili please', html)

    def test_order_detail_links_to_print_bill(self):
        body = self.client.get(f'/dashboard/order/{self.order.pk}/').content.decode()
        self.assertIn(f'/dashboard/order/{self.order.pk}/bill/print/', body)
