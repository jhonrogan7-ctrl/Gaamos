"""QR files must be tenant-safe: no cross-company filename collisions, no test
writes into the real media tree, and the printed headline is the venue's name."""
import os

from django.conf import settings

from menu.dashboard.utils import branch_poster_lines, generate_qr_for_branch
from menu.models import Branch, Company
from menu.tenancy import set_current_company, reset_current_company
from menu.tests.base import TenantTestCase


def test_media_root_isolated_from_repo():
    """The dev stack serves the repo's media/ live — tests must never write there."""
    assert not str(settings.MEDIA_ROOT).startswith(str(settings.BASE_DIR))


class QrTenantIsolationTest(TenantTestCase):
    def _branch(self, company, name='Main', slug='main'):
        return Branch.objects.create(company=company, name=name, slug=slug, address='x')

    def test_same_branch_slug_in_two_companies_gets_distinct_qr_files(self):
        b1 = self._branch(self.company)
        c2 = Company.objects.create(name='Other Co', slug='otherco')
        token = set_current_company(c2)
        try:
            b2 = self._branch(c2)
            generate_qr_for_branch(b2, 'https://otherco.zxyn.online')
        finally:
            reset_current_company(token)
        generate_qr_for_branch(b1, 'https://testco.zxyn.online')

        self.assertNotEqual(b1.qr_image, b2.qr_image)
        p1 = os.path.join(settings.MEDIA_ROOT, b1.qr_image)
        p2 = os.path.join(settings.MEDIA_ROOT, b2.qr_image)
        with open(p1, 'rb') as f1, open(p2, 'rb') as f2:
            self.assertNotEqual(f1.read(), f2.read())

    def test_branch_poster_headline_is_the_branch_name(self):
        b = self._branch(self.company)
        b.name = 'Lakeside'
        venue, label = branch_poster_lines(b)
        self.assertEqual(venue, 'Lakeside')
        self.assertEqual(label, '')

    def test_branch_poster_never_carries_the_company_name_as_a_heading(self):
        # The sheet is for one branch, so it prints one name. A venue must not
        # get two titles, whether or not the two names overlap.
        b = self._branch(self.company)
        for name in ['Lakeside', self.company.name,
                     f'{self.company.name} Restaurant']:
            b.name = name
            self.assertEqual(branch_poster_lines(b), (name, ''),
                             msg=f'{name!r} did not print as the sole heading')
