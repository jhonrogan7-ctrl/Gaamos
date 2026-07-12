from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from menu.models import Branch
from menu.tests.base import TenantTestCase


class IaTestBase(TenantTestCase):
    def setUp(self):
        super().setUp()
        U = get_user_model()
        self.owner = U.objects.create_user('boss', password='pass')
        self.make_owner(self.owner)

    def branch(self, name='Lake Center', slug='lake'):
        return Branch.objects.create(company=self.company, name=name, slug=slug)


class SidebarIaTest(IaTestBase):
    def test_sidebar_renamed_and_grouped(self):
        self.login_as(self.owner)
        body = self.client.get('/dashboard/').content.decode()
        # Global library is now Items + Categories; the old global "Menu" nav is gone.
        self.assertIn('Items\n      </a>', body)
        self.assertIn('Categories\n      </a>', body)
        self.assertNotIn('Menu\n      </a>', body)
        # Items + Categories point at the real global screens.
        self.assertIn('/dashboard/items/', body)
        self.assertIn('/dashboard/categories/', body)
        # Grouped sidebar headers (replace the old single "Manage" group).
        for grp in ('>Company<', '>Operations<', '>Account<'):
            self.assertIn(grp, body)
        self.assertNotIn('>Manage<', body)


class BranchTabShellTest(IaTestBase):
    def setUp(self):
        super().setUp()
        self.b = self.branch()
        self.login_as(self.owner)

    def test_menu_tab_shows_tab_bar_active_menu(self):
        body = self.client.get(f'/dashboard/branch/{self.b.slug}/').content.decode()
        # Tab bar present with all three tabs.
        self.assertIn('class="tabs"', body)
        for label in ('Menu', 'QR &amp; Tables', 'Orders'):
            self.assertIn(label, body)
        # Menu tab is active.
        self.assertIn('class="tab on">Menu', body)

    def test_qr_tab_renders_active(self):
        r = self.client.get(f'/dashboard/branch/{self.b.slug}/qr/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('class="tabs"', body)
        self.assertIn('class="tab on">QR &amp; Tables', body)

    def test_orders_tab_renders_active(self):
        r = self.client.get(f'/dashboard/branch/{self.b.slug}/orders/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('class="tabs"', body)
        self.assertIn('class="tab on">Orders', body)

    def test_branch_tabs_keep_branches_nav_highlighted(self):
        # active_tab='branches' so the sidebar Branches entry stays lit on all tabs.
        for suffix in ('', 'qr/', 'orders/'):
            body = self.client.get(f'/dashboard/branch/{self.b.slug}/{suffix}').content.decode()
            self.assertIn('class="nav on"', body)


class BranchTabTenancyTest(IaTestBase):
    def test_other_company_branch_forbidden(self):
        from menu.models import Company
        from menu.tenancy import set_current_company, reset_current_company
        other = Company.objects.create(name='Other', slug='other')
        tok = set_current_company(other)
        try:
            stranger = Branch.objects.create(company=other, name='Far', slug='far')
        finally:
            reset_current_company(tok)
        self.login_as(self.owner)  # owner of self.company, not `other`
        for suffix in ('qr/', 'orders/'):
            r = self.client.get(f'/dashboard/branch/{stranger.slug}/{suffix}')
            # Foreign branch is outside our tenant scope → 404 (hidden), still denied.
            self.assertEqual(r.status_code, 404, suffix)


class TabCssTest(SimpleTestCase):
    def test_tab_component_present(self):
        css = (Path(settings.BASE_DIR) / 'static/css/app.css').read_text()
        for sel in ('.tabs', '.tab'):
            self.assertIn(sel, css, f'missing tab style {sel}')


class BranchQrTabContentTest(IaTestBase):
    def setUp(self):
        super().setUp()
        self.b = self.branch()
        self.login_as(self.owner)

    def test_qr_tab_has_branch_qr_and_tables_stub(self):
        body = self.client.get(f'/dashboard/branch/{self.b.slug}/qr/').content.decode()
        # Menu/general QR management for THIS branch.
        self.assertIn('Generate QR', body)
        self.assertIn(f'/?branch={self.b.slug}', body)
        # Table QRs section is real as of Spec 2.
        self.assertIn('Table QRs', body)
        self.assertIn('Add table', body)


class BranchOrdersTabContentTest(IaTestBase):
    def setUp(self):
        super().setUp()
        self.b = self.branch()
        self.login_as(self.owner)

    def test_orders_tab_is_branch_scoped_sample_with_notice(self):
        body = self.client.get(f'/dashboard/branch/{self.b.slug}/orders/').content.decode()
        # Scoped to this branch.
        self.assertIn(self.b.name, body)
        # Spec 3: ordering is live; with no tables the branch shows takeaway ordering.
        self.assertIn('Takeaway ordering active', body)


class GlobalQrAggregateTest(IaTestBase):
    def setUp(self):
        super().setUp()
        self.b = self.branch()
        self.login_as(self.owner)

    def test_global_qr_links_into_branch_tab_and_no_false_claim(self):
        body = self.client.get('/dashboard/qr/').content.decode()
        # Links into the per-branch QR tab (the single editing surface).
        self.assertIn(f'/dashboard/branch/{self.b.slug}/qr/', body)
        # The old inaccurate "each table gets its own QR" claim is gone.
        self.assertNotIn('Each table gets its own QR', body)

    def test_branches_card_qr_action_targets_branch_tab(self):
        body = self.client.get('/dashboard/branches/').content.decode()
        self.assertIn(f'/dashboard/branch/{self.b.slug}/qr/', body)


class GlobalOrdersReframeTest(IaTestBase):
    def test_global_orders_is_all_branches_live_queue(self):
        # Spec 3: global Orders is the real all-branches live queue (no longer a sample).
        self.login_as(self.owner)
        body = self.client.get('/dashboard/orders/').content.decode()
        self.assertIn('All branches', body)
        self.assertIn('Live order queue', body)
