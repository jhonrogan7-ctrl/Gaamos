from django.test import TestCase

from menu.models import Company
from menu.tenancy import set_current_company, reset_current_company


class TenantTestCase(TestCase):
    """Base for tests that exercise tenant-scoped models. Creates a default company
    and activates it for the duration of each test, resetting context afterward."""

    company_slug = 'testco'

    def setUp(self):
        super().setUp()
        self.company = Company.objects.create(name='Test Co', slug=self.company_slug)
        self._token = set_current_company(self.company)

    def tearDown(self):
        reset_current_company(self._token)
        super().tearDown()
