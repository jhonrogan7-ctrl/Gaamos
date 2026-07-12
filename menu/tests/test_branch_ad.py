import base64
import tempfile

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.urls import reverse

from menu.dashboard.views import MAX_IMAGE_BYTES

from menu.models import Branch, BranchAd, Company
from menu.tenancy import (
    TenantContextRequired, reset_current_company, set_current_company,
)
from menu.tests.base import TenantTestCase

# 1×1 transparent PNG — content is never parsed (no focal point for ads),
# but keep uploads realistic.
TINY_PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8'
    '/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=='
)


class BranchAdModelTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')

    def test_company_autostamped_from_context(self):
        ad = BranchAd.objects.create(branch=self.branch, image_url='/media/ads/x.png')
        self.assertEqual(ad.company_id, self.company.id)

    def test_inactive_by_default(self):
        ad = BranchAd.objects.create(branch=self.branch)
        self.assertFalse(ad.is_active)

    def test_one_ad_per_branch(self):
        BranchAd.objects.create(branch=self.branch)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BranchAd.objects.create(branch=self.branch)

    def test_fail_closed_without_company_context(self):
        BranchAd.objects.create(branch=self.branch)
        reset_current_company(self._token)
        try:
            with self.assertRaises(TenantContextRequired):
                list(BranchAd.objects.all())
        finally:
            self._token = set_current_company(self.company)

    def test_scoped_to_current_company(self):
        BranchAd.objects.create(branch=self.branch)
        other = Company.objects.create(name='Other', slug='other')
        tok = set_current_company(other)
        try:
            other_branch = Branch.objects.create(company=other, name='Far', slug='far')
            BranchAd.objects.create(branch=other_branch)
            self.assertEqual(BranchAd.objects.count(), 1)
            self.assertEqual(BranchAd.objects.first().branch_id, other_branch.id)
        finally:
            reset_current_company(tok)
        self.assertEqual(BranchAd.objects.count(), 1)
        self.assertEqual(BranchAd.objects.first().branch_id, self.branch.id)

    def test_clean_rejects_foreign_company_branch(self):
        other = Company.objects.create(name='Other', slug='other')
        tok = set_current_company(other)
        try:
            foreign_branch = Branch.objects.create(company=other, name='Far', slug='far')
        finally:
            reset_current_company(tok)
        ad = BranchAd(company=self.company, branch=foreign_branch)
        with self.assertRaises(ValidationError):
            ad.clean()


class PromotionTabAccessTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')
        self.other_branch = Branch.objects.create(company=self.company, name='Hill', slug='hill')
        User = get_user_model()
        self.owner = User.objects.create_user('owner', password='pass')
        self.make_owner(self.owner)
        self.mgr = User.objects.create_user('mgr', password='pass')
        self.make_manager(self.mgr, branches=[self.branch])
        self.other_mgr = User.objects.create_user('othermgr', password='pass')
        self.make_manager(self.other_mgr, branches=[self.other_branch])
        self.url = reverse('dashboard:branch_promotion', args=[self.branch.slug])

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)

    def test_owner_sees_empty_state(self):
        self.login_as(self.owner)
        resp = self.client.get(self.url)
        self.assertContains(resp, 'No promotion yet')

    def test_branch_manager_can_view(self):
        self.login_as(self.mgr)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    def test_other_branch_manager_forbidden(self):
        self.login_as(self.other_mgr)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 403)

    def test_existing_ad_previewed(self):
        BranchAd.objects.create(branch=self.branch, image_url='/media/ads/ad_1.png')
        self.login_as(self.owner)
        resp = self.client.get(self.url)
        self.assertContains(resp, '/media/ads/ad_1.png')

    def test_tab_link_present_on_qr_tab(self):
        self.login_as(self.owner)
        resp = self.client.get(reverse('dashboard:branch_qr', args=[self.branch.slug]))
        self.assertContains(resp, self.url)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PromotionManageTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')
        self.other_branch = Branch.objects.create(company=self.company, name='Hill', slug='hill')
        User = get_user_model()
        self.owner = User.objects.create_user('owner', password='pass')
        self.make_owner(self.owner)
        self.other_mgr = User.objects.create_user('othermgr', password='pass')
        self.make_manager(self.other_mgr, branches=[self.other_branch])
        self.tab_url = reverse('dashboard:branch_promotion', args=[self.branch.slug])
        self.save_url = reverse('dashboard:branch_promotion_save', args=[self.branch.slug])
        self.toggle_url = reverse('dashboard:branch_promotion_toggle', args=[self.branch.slug])
        self.delete_url = reverse('dashboard:branch_promotion_delete', args=[self.branch.slug])

    def _png(self, name='promo.png'):
        return SimpleUploadedFile(name, TINY_PNG, content_type='image/png')

    def test_upload_creates_ad_inactive(self):
        self.login_as(self.owner)
        resp = self.client.post(self.save_url, {'image_file': self._png()})
        self.assertRedirects(resp, self.tab_url)
        ad = BranchAd.objects.get(branch=self.branch)
        self.assertTrue(ad.image_url.startswith('/media/ads/ad_'))
        self.assertFalse(ad.is_active)

    def test_upload_replaces_and_bumps_version(self):
        self.login_as(self.owner)
        self.client.post(self.save_url, {'image_file': self._png()})
        ad = BranchAd.objects.get(branch=self.branch)
        first_version = ad.updated_at
        self.client.post(self.save_url, {'image_file': self._png('new.jpg')})
        ad.refresh_from_db()
        self.assertTrue(ad.image_url.endswith('.jpg'))
        self.assertGreater(ad.updated_at, first_version)
        self.assertEqual(BranchAd.objects.filter(branch=self.branch).count(), 1)

    def test_bad_extension_rejected_no_row(self):
        self.login_as(self.owner)
        resp = self.client.post(self.save_url, {
            'image_file': SimpleUploadedFile('promo.gif', b'GIF89a', content_type='image/gif')})
        self.assertContains(resp, 'JPG, PNG or WEBP')
        self.assertFalse(BranchAd.objects.filter(branch=self.branch).exists())

    def test_oversize_rejected(self):
        self.login_as(self.owner)
        big = SimpleUploadedFile('promo.png', b'0' * (MAX_IMAGE_BYTES + 1),
                                 content_type='image/png')
        resp = self.client.post(self.save_url, {'image_file': big})
        self.assertContains(resp, 'JPG, PNG or WEBP')
        self.assertFalse(BranchAd.objects.filter(branch=self.branch).exists())

    def test_missing_file_shows_error(self):
        self.login_as(self.owner)
        resp = self.client.post(self.save_url, {})
        self.assertContains(resp, 'Choose an image')

    def test_toggle_flips_active_without_version_bump(self):
        ad = BranchAd.objects.create(branch=self.branch, image_url='/media/ads/ad_1.png')
        version = ad.updated_at
        self.login_as(self.owner)
        self.client.post(self.toggle_url)
        ad.refresh_from_db()
        self.assertTrue(ad.is_active)
        self.assertEqual(ad.updated_at, version)
        self.client.post(self.toggle_url)
        ad.refresh_from_db()
        self.assertFalse(ad.is_active)

    def test_toggle_without_ad_404(self):
        self.login_as(self.owner)
        resp = self.client.post(self.toggle_url)
        self.assertEqual(resp.status_code, 404)

    def test_delete_removes_row(self):
        BranchAd.objects.create(branch=self.branch, image_url='/media/ads/ad_1.png')
        self.login_as(self.owner)
        resp = self.client.post(self.delete_url)
        self.assertRedirects(resp, self.tab_url)
        self.assertFalse(BranchAd.objects.filter(branch=self.branch).exists())

    def test_other_branch_manager_forbidden_on_all_posts(self):
        BranchAd.objects.create(branch=self.branch, image_url='/media/ads/ad_1.png')
        self.login_as(self.other_mgr)
        for url in (self.save_url, self.toggle_url, self.delete_url):
            resp = self.client.post(url, {'image_file': self._png()})
            self.assertEqual(resp.status_code, 403)

    def test_get_not_allowed_on_posts(self):
        self.login_as(self.owner)
        for url in (self.save_url, self.toggle_url, self.delete_url):
            self.assertEqual(self.client.get(url).status_code, 405)


class GuestAdOverlayTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')

    def _menu(self):
        return self.client.get('/', {'branch': self.branch.slug})

    def test_active_ad_renders_overlay(self):
        ad = BranchAd.objects.create(branch=self.branch,
                                     image_url='/media/ads/ad_1.png', is_active=True)
        resp = self._menu()
        self.assertContains(resp, 'ad-overlay')
        self.assertContains(resp, '/media/ads/ad_1.png')
        self.assertContains(resp, f"adOverlay('lake', {int(ad.updated_at.timestamp())})")

    def test_inactive_ad_not_rendered(self):
        BranchAd.objects.create(branch=self.branch,
                                image_url='/media/ads/ad_1.png', is_active=False)
        self.assertNotContains(self._menu(), 'ad-overlay')

    def test_no_ad_not_rendered(self):
        self.assertNotContains(self._menu(), 'ad-overlay')

    def test_active_ad_without_image_not_rendered(self):
        BranchAd.objects.create(branch=self.branch, image_url='', is_active=True)
        self.assertNotContains(self._menu(), 'ad-overlay')

    def test_ad_is_per_branch(self):
        other = Branch.objects.create(company=self.company, name='Hill', slug='hill')
        BranchAd.objects.create(branch=other,
                                image_url='/media/ads/ad_9.png', is_active=True)
        self.assertNotContains(self._menu(), 'ad-overlay')

    def test_cross_tenant_ad_never_leaks(self):
        other_co = Company.objects.create(name='Other', slug='other')
        tok = set_current_company(other_co)
        try:
            other_branch = Branch.objects.create(company=other_co, name='Far', slug='lake')
            BranchAd.objects.create(branch=other_branch,
                                    image_url='/media/ads/theirs.png', is_active=True)
        finally:
            reset_current_company(tok)
        resp = self._menu()  # host is testco's subdomain; same branch slug 'lake'
        self.assertNotContains(resp, '/media/ads/theirs.png')
