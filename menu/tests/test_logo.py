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


import json

from menu.models import Branch


class GuestLogoPayloadTest(TenantTestCase):
    def _payload(self):
        resp = self.client.get('/')
        m = re.search(
            r'<script id="menu-data" type="application/json">(.*?)</script>',
            resp.content.decode(), re.DOTALL)
        return json.loads(m.group(1))

    def test_payload_has_logo_url(self):
        Branch.objects.create(company=self.company, name='Lakeside', slug='lakeside')
        self.company.logo_url = '/media/logos/logo_1.png?v=42'
        self.company.save(update_fields=['logo_url'])
        payload = self._payload()
        self.assertEqual(payload['restaurant']['logo_url'], '/media/logos/logo_1.png?v=42')

    def test_payload_logo_url_blank_by_default(self):
        Branch.objects.create(company=self.company, name='Lakeside', slug='lakeside')
        self.assertEqual(self._payload()['restaurant']['logo_url'], '')


class BrandbarTemplateTest(TenantTestCase):
    def _brandbar(self):
        return (Path(settings.BASE_DIR) / 'templates/menu/_brandbar.html').read_text()

    def test_title_is_branch_venue_name(self):
        html = self._brandbar()
        self.assertIn('x-text="venueName()"', html)
        self.assertNotIn('x-text="restaurant.name"', html)

    def test_small_line_is_address_only(self):
        html = self._brandbar()
        self.assertIn('x-text="branch.address"', html)
        self.assertNotIn("branch.name + ", html)

    def test_logo_with_monogram_fallback(self):
        html = self._brandbar()
        self.assertIn('restaurant.logo_url', html)
        self.assertIn('g-logo', html)
        self.assertIn('monogram()', html)

    def test_about_sheet_logo_fallback(self):
        html = (Path(settings.BASE_DIR) / 'templates/menu/index.html').read_text()
        self.assertIn('g-mono--lg g-mono--img', html)

    def test_monogram_derives_from_venue_name(self):
        js = (Path(settings.BASE_DIR) / 'static/js/app.js').read_text()
        self.assertIn('venueName()', js)

    def test_guest_logo_css_built(self):
        css = (Path(settings.BASE_DIR) / 'static/css/app.css').read_text()
        self.assertRegex(css, r'[}{]\.g-logo\{')
        self.assertRegex(css, r'[}{]\.g-mono--img\{')


class SidebarLogoTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.owner = User.objects.create_user('own2', password='pass')
        self.make_owner(self.owner)
        self.login_as(self.owner)

    def test_letter_mark_without_logo(self):
        resp = self.client.get('/dashboard/')
        self.assertContains(resp, '<div class="logo">T</div>', html=True)

    def test_logo_image_when_set(self):
        self.company.logo_url = '/media/logos/logo_1.png?v=7'
        self.company.save(update_fields=['logo_url'])
        resp = self.client.get('/dashboard/')
        self.assertContains(resp, 'logo--img')
        self.assertContains(resp, '/media/logos/logo_1.png?v=7')

    def test_sidebar_logo_css_built(self):
        css = (Path(settings.BASE_DIR) / 'static/css/app.css').read_text()
        self.assertRegex(css, r'[}{]\.side .brand \.logo--img\{'.replace(' ', r'\s*'))
