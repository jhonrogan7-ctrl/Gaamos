from django.conf import settings
from django.test import TestCase

from menu.models import Company
from menu.tenancy import set_current_company, reset_current_company


class TenantTestCase(TestCase):
    """Base for tests that exercise tenant-scoped models. Creates a default company
    and activates it for the duration of each test, resetting context afterward.

    Requests are addressed to the company's subdomain by default. Since apex/reserved
    hosts no longer resolve to a tenant (the single-company shim was removed), a bare
    ``testserver`` request would resolve to no company; the default host below makes the
    test client reach this company's guest menu / dashboard as a real browser would.
    Individual requests may still pass their own ``HTTP_HOST`` to override this."""

    company_slug = 'testco'

    def setUp(self):
        super().setUp()
        self.company = Company.objects.create(name='Test Co', slug=self.company_slug)
        self._token = set_current_company(self.company)
        self.host = f'{self.company_slug}.{settings.BASE_DOMAIN}'
        self.client.defaults['HTTP_HOST'] = self.host

    def tearDown(self):
        reset_current_company(self._token)
        super().tearDown()

    def make_owner(self, user, company=None):
        from menu.models import Membership
        return Membership.objects.create(
            user=user, company=company or self.company, role=Membership.ROLE_OWNER)

    def make_manager(self, user, branches=(), company=None):
        from menu.models import Membership
        m = Membership.objects.create(
            user=user, company=company or self.company, role=Membership.ROLE_MANAGER)
        if branches:
            m.branches.set(branches)
        return m

    def login_as(self, user, password='pass'):
        self.assertTrue(self.client.login(username=user.username, password=password))
        return user
