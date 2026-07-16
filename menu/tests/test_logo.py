import os

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile

from menu.dashboard.views import MAX_IMAGE_BYTES, save_logo_image
from menu.tests.base import TenantTestCase
from menu.tests.test_branch_ad import TINY_PNG


class CompanyLogoFieldTest(TenantTestCase):
    def test_logo_url_blank_by_default(self):
        self.assertEqual(self.company.logo_url, '')


class SaveLogoImageTest(TenantTestCase):
    def _png(self, name='logo.png', content=TINY_PNG):
        return SimpleUploadedFile(name, content, content_type='image/png')

    def test_saves_file_and_stores_versioned_url(self):
        url = save_logo_image(self.company, self._png())
        expected_path = f'{settings.MEDIA_URL}logos/logo_{self.company.pk}.png?v='
        self.assertTrue(url.startswith(expected_path), url)
        self.company.refresh_from_db()
        self.assertEqual(self.company.logo_url, url)
        self.assertTrue(os.path.exists(os.path.join(
            settings.MEDIA_ROOT, 'logos', f'logo_{self.company.pk}.png')))

    def test_rejects_bad_extension(self):
        upload = SimpleUploadedFile('logo.gif', b'gif89a', content_type='image/gif')
        self.assertIsNone(save_logo_image(self.company, upload))
        self.company.refresh_from_db()
        self.assertEqual(self.company.logo_url, '')

    def test_rejects_oversize(self):
        upload = self._png(content=b'0' * (MAX_IMAGE_BYTES + 1))
        self.assertIsNone(save_logo_image(self.company, upload))
        self.company.refresh_from_db()
        self.assertEqual(self.company.logo_url, '')
