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
