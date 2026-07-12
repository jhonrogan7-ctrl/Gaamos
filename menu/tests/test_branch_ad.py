import base64

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse

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
