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


from django.contrib.auth import get_user_model


class SettingsLogoEndpointTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.owner = User.objects.create_user('own', password='pass')
        self.make_owner(self.owner)
        self.manager = User.objects.create_user('mgr', password='pass')
        self.make_manager(self.manager)

    def _png(self):
        return SimpleUploadedFile('logo.png', TINY_PNG, content_type='image/png')

    def test_owner_uploads_logo(self):
        self.login_as(self.owner)
        resp = self.client.post('/dashboard/settings/logo/', {'logo': self._png()})
        self.assertRedirects(resp, '/dashboard/settings/')
        self.company.refresh_from_db()
        self.assertIn(f'logos/logo_{self.company.pk}.png?v=', self.company.logo_url)

    def test_invalid_upload_rerenders_with_error(self):
        self.login_as(self.owner)
        bad = SimpleUploadedFile('logo.gif', b'gif89a', content_type='image/gif')
        resp = self.client.post('/dashboard/settings/logo/', {'logo': bad})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Logo must be JPG, PNG or WEBP')
        self.company.refresh_from_db()
        self.assertEqual(self.company.logo_url, '')

    def test_missing_file_rerenders_with_error(self):
        self.login_as(self.owner)
        resp = self.client.post('/dashboard/settings/logo/', {})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Logo must be JPG, PNG or WEBP')

    def test_manager_blocked(self):
        self.login_as(self.manager)
        resp = self.client.post('/dashboard/settings/logo/', {'logo': self._png()})
        self.assertEqual(resp.status_code, 403)

    def test_owner_removes_logo(self):
        self.company.logo_url = '/media/logos/logo_1.png?v=1'
        self.company.save(update_fields=['logo_url'])
        self.login_as(self.owner)
        resp = self.client.post('/dashboard/settings/logo/delete/')
        self.assertRedirects(resp, '/dashboard/settings/')
        self.company.refresh_from_db()
        self.assertEqual(self.company.logo_url, '')

    def test_settings_page_shows_logo_card(self):
        self.login_as(self.owner)
        resp = self.client.get('/dashboard/settings/')
        self.assertContains(resp, 'id="logo"')
        self.assertContains(resp, 'Upload logo')
        self.company.logo_url = '/media/logos/logo_1.png?v=1'
        self.company.save(update_fields=['logo_url'])
        resp = self.client.get('/dashboard/settings/')
        self.assertContains(resp, 'Replace logo')
        self.assertContains(resp, '/media/logos/logo_1.png?v=1')


import re
from pathlib import Path


class LogoCssBuiltTest(TenantTestCase):
    def _css(self):
        return (Path(settings.BASE_DIR) / 'static/css/app.css').read_text()

    def test_logo_card_classes_survive_purge(self):
        css = self._css()
        for cls in ('logo-row', 'logo-preview', 'logo-actions'):
            self.assertRegex(css, r'[}{]\.' + cls + r'\{',
                             f'.{cls} rule missing from built app.css')
