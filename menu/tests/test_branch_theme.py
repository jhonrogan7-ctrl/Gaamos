"""Branch Theme tab: picker partial, tab rendering, save endpoint, access."""
from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import SimpleTestCase

from menu.models import Branch, Company
from menu.tenancy import set_current_company, reset_current_company
from menu.tests.base import TenantTestCase


def render_picker(**kwargs):
    ctx = Context(kwargs)
    args = ' '.join(f'{k}={k}' for k in kwargs)
    return Template('{% load theme_tags %}{% theme_picker ' + args + ' %}').render(ctx)


class ThemePickerInheritCardTest(SimpleTestCase):
    def test_submit_mode_inherit_card_is_submit_button(self):
        html = render_picker(current='', include_inherit=True)
        self.assertIn('name="menu_theme" value=""', html)
        self.assertIn('Company default', html)
        self.assertNotIn('bTheme', html)  # no Alpine leakage in submit mode
        # inherit + 6 themes, all submit buttons
        self.assertEqual(html.count('name="menu_theme"'), 7)

    def test_inherit_card_on_only_when_inheriting(self):
        html = render_picker(current='', include_inherit=True)
        self.assertEqual(html.count('class="theme on"'), 1)
        self.assertLess(html.index('class="theme on"'), html.index('Classic Fast Food'))
        html = render_picker(current='eco', include_inherit=True)
        self.assertEqual(html.count('class="theme on"'), 1)
        self.assertGreater(html.index('class="theme on"'), html.index('Company default'))

    def test_alpine_mode_unchanged(self):
        html = render_picker(current='', include_inherit=True, alpine=True)
        self.assertIn('@click="bTheme=\'\'"', html)
        self.assertEqual(html.count('@click="bTheme='), 7)
        self.assertNotIn('type="submit"', html)

    def test_settings_mode_without_inherit_unchanged(self):
        html = render_picker(current='eco')
        self.assertNotIn('Company default', html)
        self.assertEqual(html.count('name="menu_theme"'), 6)


class BranchThemeTabTest(TenantTestCase):
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
        self.url = f'/dashboard/branch/{self.branch.slug}/theme/'
        self.save_url = f'/dashboard/branch/{self.branch.slug}/theme/save/'

    def test_anonymous_redirected_to_login(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_tab_renders_inherit_plus_six_and_view_menu_link(self):
        self.login_as(self.owner)
        body = self.client.get(self.url).content.decode()
        self.assertEqual(body.count('name="menu_theme"'), 7)
        self.assertIn('Company default', body)
        self.assertIn('Appetite Stimulators', body)
        self.assertIn('Trust &amp; Comfort', body)
        self.assertIn(f'/?branch={self.branch.slug}', body)   # View menu link
        self.assertIn(self.save_url, body)                    # form action

    def test_current_theme_marked_on(self):
        self.branch.menu_theme = 'cozy'
        self.branch.save()
        self.login_as(self.owner)
        body = self.client.get(self.url).content.decode()
        self.assertEqual(body.count('class="theme on"'), 1)
        self.assertGreater(body.index('class="theme on"'), body.index('Company default'))

    def test_branch_manager_can_view(self):
        self.login_as(self.mgr)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_other_branch_manager_forbidden(self):
        self.login_as(self.other_mgr)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_foreign_tenant_branch_404(self):
        other = Company.objects.create(name='Other', slug='other')
        tok = set_current_company(other)
        try:
            Branch.objects.create(company=other, name='Far', slug='far')
        finally:
            reset_current_company(tok)
        self.login_as(self.owner)
        self.assertEqual(
            self.client.get('/dashboard/branch/far/theme/').status_code, 404)

    def test_tab_link_present_on_promotion_tab(self):
        self.login_as(self.owner)
        resp = self.client.get(f'/dashboard/branch/{self.branch.slug}/promotion/')
        self.assertContains(resp, self.url)


class BranchThemeSaveTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')
        User = get_user_model()
        self.owner = User.objects.create_user('owner', password='pass')
        self.make_owner(self.owner)
        self.save_url = f'/dashboard/branch/{self.branch.slug}/theme/save/'

    def test_save_persists_valid_slug_and_redirects(self):
        self.login_as(self.owner)
        resp = self.client.post(self.save_url, {'menu_theme': 'citrus'})
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.menu_theme, 'citrus')
        self.assertRedirects(resp, f'/dashboard/branch/{self.branch.slug}/theme/',
                             fetch_redirect_response=False)

    def test_empty_value_sets_inherit(self):
        self.branch.menu_theme = 'herbal'
        self.branch.save()
        self.login_as(self.owner)
        self.client.post(self.save_url, {'menu_theme': ''})
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.menu_theme, '')

    def test_garbage_slug_coerces_to_inherit(self):
        self.branch.menu_theme = 'herbal'
        self.branch.save()
        self.login_as(self.owner)
        self.client.post(self.save_url, {'menu_theme': 'neon'})
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.menu_theme, '')

    def test_get_on_save_url_is_405(self):
        self.login_as(self.owner)
        self.assertEqual(self.client.get(self.save_url).status_code, 405)

    def test_other_branch_manager_forbidden_on_post(self):
        User = get_user_model()
        other_branch = Branch.objects.create(company=self.company, name='Hill', slug='hill')
        other_mgr = User.objects.create_user('othermgr', password='pass')
        self.make_manager(other_mgr, branches=[other_branch])
        self.login_as(other_mgr)
        resp = self.client.post(self.save_url, {'menu_theme': 'eco'})
        self.assertEqual(resp.status_code, 403)
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.menu_theme, '')
