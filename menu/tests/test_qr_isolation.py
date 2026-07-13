"""QR files must be tenant-safe: no cross-company filename collisions, no test
writes into the real media tree, and the printed caption is the venue's name."""
import os
from unittest.mock import patch

from django.conf import settings

from menu.dashboard.utils import generate_qr_for_branch
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

    def test_branch_qr_caption_is_company_name(self):
        b = self._branch(self.company)
        with patch('menu.dashboard.utils.render_qr_png', return_value=b'png') as m:
            generate_qr_for_branch(b, 'https://testco.zxyn.online')
        m.assert_called_once_with('https://testco.zxyn.online/?branch=main',
                                  self.company.name)
