from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from menu.models import Branch, Company, Table, generate_table_code
from menu.tenancy import set_current_company, reset_current_company
from menu.tests.base import TenantTestCase


class TableModelTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')

    def test_code_autofilled_and_unique(self):
        a = Table.objects.create(branch=self.branch, label='1')
        b = Table.objects.create(branch=self.branch, label='2')
        self.assertTrue(a.code)
        self.assertTrue(b.code)
        self.assertNotEqual(a.code, b.code)

    def test_code_generator_is_url_safe_unambiguous(self):
        code = generate_table_code()
        self.assertTrue(code)
        # no visually ambiguous chars
        self.assertFalse(set(code) & set('0Oo1lI'))

    def test_company_autostamped_from_context(self):
        t = Table.objects.create(branch=self.branch, label='7')
        self.assertEqual(t.company_id, self.company.id)

    def test_ordering(self):
        t2 = Table.objects.create(branch=self.branch, label='b', display_order=2)
        t1 = Table.objects.create(branch=self.branch, label='a', display_order=1)
        self.assertEqual(list(Table.objects.all()), [t1, t2])

    def test_clean_rejects_foreign_company_branch(self):
        other = Company.objects.create(name='Other', slug='other')
        tok = set_current_company(other)
        try:
            foreign_branch = Branch.objects.create(company=other, name='Far', slug='far')
        finally:
            reset_current_company(tok)
        # company in context is self.company; branch belongs to `other`
        t = Table(company=self.company, branch=foreign_branch, label='x')
        with self.assertRaises(ValidationError):
            t.clean()


class QrHelpersTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')

    def test_render_qr_png_returns_png_bytes(self):
        from menu.dashboard.utils import render_qr_png
        data = render_qr_png('https://example.com/?branch=lake&t=abc123', 'Table 7')
        self.assertTrue(data.startswith(b'\x89PNG'))

    def test_table_qr_url_shape(self):
        from menu.dashboard.utils import table_qr_url
        t = Table.objects.create(branch=self.branch, label='7', code='abc123')
        url = table_qr_url(self.branch, t)
        self.assertIn('?branch=lake', url)
        self.assertIn('&t=abc123', url)

    def test_render_table_qr_pdf_returns_pdf(self):
        from menu.dashboard.utils import render_table_qr_pdf
        tables = [Table.objects.create(branch=self.branch, label=str(i)) for i in range(2)]
        data = render_table_qr_pdf(self.branch, tables)
        self.assertTrue(data.startswith(b'%PDF'))


class TableCrudTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        U = get_user_model()
        self.owner = U.objects.create_user('boss', password='pass')
        self.make_owner(self.owner)
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')
        self.login_as(self.owner)

    def test_add_one(self):
        r = self.client.post(f'/dashboard/branch/{self.branch.slug}/tables/add/', {'label': 'Patio 2'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Table.objects.filter(branch=self.branch, label='Patio 2').count(), 1)

    def test_bulk_range_creates_and_skips_existing(self):
        Table.objects.create(branch=self.branch, label='2')
        self.client.post(f'/dashboard/branch/{self.branch.slug}/tables/bulk/', {'start': '1', 'end': '4'})
        labels = sorted(Table.objects.filter(branch=self.branch).values_list('label', flat=True))
        self.assertEqual(labels, ['1', '2', '3', '4'])  # '2' not duplicated

    def test_bulk_caps_oversized_range(self):
        self.client.post(f'/dashboard/branch/{self.branch.slug}/tables/bulk/', {'start': '1', 'end': '500'})
        self.assertEqual(Table.objects.filter(branch=self.branch).count(), 0)

    def test_edit_keeps_code(self):
        t = Table.objects.create(branch=self.branch, label='7')
        code = t.code
        self.client.post(f'/dashboard/branch/{self.branch.slug}/table/{t.code}/edit/', {'label': 'Window'})
        t.refresh_from_db()
        self.assertEqual(t.label, 'Window')
        self.assertEqual(t.code, code)

    def test_delete(self):
        t = Table.objects.create(branch=self.branch, label='7')
        self.client.post(f'/dashboard/branch/{self.branch.slug}/table/{t.code}/delete/')
        self.assertFalse(Table.objects.filter(pk=t.pk).exists())


class TableCrudTenancyTest(TenantTestCase):
    def test_other_company_branch_forbidden(self):
        U = get_user_model()
        self.owner = U.objects.create_user('boss', password='pass')
        self.make_owner(self.owner)
        other = Company.objects.create(name='Other', slug='other')
        tok = set_current_company(other)
        try:
            stranger = Branch.objects.create(company=other, name='Far', slug='far')
        finally:
            reset_current_company(tok)
        self.login_as(self.owner)
        r = self.client.post(f'/dashboard/branch/{stranger.slug}/tables/add/', {'label': 'x'})
        self.assertEqual(r.status_code, 403)


class TableQrEndpointTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        U = get_user_model()
        self.owner = U.objects.create_user('boss', password='pass')
        self.make_owner(self.owner)
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')
        self.table = Table.objects.create(branch=self.branch, label='7', code='abc123')
        self.login_as(self.owner)

    def test_table_qr_png(self):
        r = self.client.get(f'/dashboard/branch/{self.branch.slug}/table/{self.table.code}/qr/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'image/png')
        self.assertTrue(r.content.startswith(b'\x89PNG'))

    def test_table_qr_pdf(self):
        r = self.client.get(f'/dashboard/branch/{self.branch.slug}/table/{self.table.code}/qr/?format=pdf')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')

    def test_download_all_pdf(self):
        Table.objects.create(branch=self.branch, label='8')
        r = self.client.get(f'/dashboard/branch/{self.branch.slug}/tables/qr.pdf')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')

    def test_table_qr_forbidden_other_company(self):
        other = Company.objects.create(name='Other', slug='other')
        tok = set_current_company(other)
        try:
            stranger = Branch.objects.create(company=other, name='Far', slug='far')
            ftable = Table.objects.create(branch=stranger, label='1', code='zzz999')
        finally:
            reset_current_company(tok)
        r = self.client.get(f'/dashboard/branch/{stranger.slug}/table/{ftable.code}/qr/')
        self.assertEqual(r.status_code, 403)


class QrTabContentTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        U = get_user_model()
        self.owner = U.objects.create_user('boss', password='pass')
        self.make_owner(self.owner)
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')
        self.login_as(self.owner)

    def test_tab_shows_real_table_section_not_stub(self):
        Table.objects.create(branch=self.branch, label='7', code='abc123')
        body = self.client.get(f'/dashboard/branch/{self.branch.slug}/qr/').content.decode()
        # Spec-1 stub copy is gone.
        self.assertNotIn('coming with ordering', body)
        # Bulk + add forms present.
        self.assertIn(f'/dashboard/branch/{self.branch.slug}/tables/bulk/', body)
        self.assertIn(f'/dashboard/branch/{self.branch.slug}/tables/add/', body)
        # Real table row + its lazy QR link + download-all.
        self.assertIn('abc123', body)
        self.assertIn(f'/dashboard/branch/{self.branch.slug}/table/abc123/qr/', body)
        self.assertIn(f'/dashboard/branch/{self.branch.slug}/tables/qr.pdf', body)


class OrdersGateTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        U = get_user_model()
        self.owner = U.objects.create_user('boss', password='pass')
        self.make_owner(self.owner)
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')
        self.login_as(self.owner)

    def test_gate_without_tables(self):
        body = self.client.get(f'/dashboard/branch/{self.branch.slug}/orders/').content.decode()
        self.assertIn('Add table QRs to enable ordering', body)
        self.assertIn('Sample data', body)  # queue still sample

    def test_gate_with_tables(self):
        Table.objects.create(branch=self.branch, label='1')
        body = self.client.get(f'/dashboard/branch/{self.branch.slug}/orders/').content.decode()
        self.assertIn('Ordering ready', body)
        self.assertIn('Sample data', body)  # queue still sample until Spec 3
