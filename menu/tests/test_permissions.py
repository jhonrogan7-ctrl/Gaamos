from django.contrib.auth.models import AnonymousUser, User
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import RequestFactory

from menu.middleware import MembershipMiddleware
from menu.models import Branch, Category, Company, Membership, MenuItem
from menu.permissions import can_manage_branch, ensure_can_manage_branch
from menu.tests.base import TenantTestCase


class MembershipModelTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='u', password='pass')

    def test_role_defaults_to_manager(self):
        m = Membership.objects.create(user=self.user, company=self.company)
        self.assertEqual(m.role, Membership.ROLE_MANAGER)
        self.assertFalse(m.is_owner)

    def test_is_owner_true_for_owner_role(self):
        m = Membership.objects.create(user=self.user, company=self.company,
                                      role=Membership.ROLE_OWNER)
        self.assertTrue(m.is_owner)

    def test_one_membership_per_user_per_company(self):
        Membership.objects.create(user=self.user, company=self.company)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Membership.objects.create(user=self.user, company=self.company)

    def test_same_user_can_join_two_companies(self):
        other = Company.objects.create(name='Other', slug='other')
        Membership.objects.create(user=self.user, company=self.company)
        Membership.objects.create(user=self.user, company=other)
        self.assertEqual(self.user.memberships.count(), 2)

    def test_manager_branch_assignment(self):
        branch = Branch.objects.create(company=self.company, name='Main', slug='main', address='X')
        m = Membership.objects.create(user=self.user, company=self.company,
                                      role=Membership.ROLE_MANAGER)
        m.branches.add(branch)
        self.assertEqual(list(m.branches.all()), [branch])


class MembershipMiddlewareTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.rf = RequestFactory()
        self.user = User.objects.create_user(username='u', password='pass')
        self.mw = MembershipMiddleware(lambda req: req)  # echo request back

    def _run(self, user):
        req = self.rf.get('/dashboard/')
        req.user = user
        req.company = self.company
        self.mw(req)
        return req

    def test_member_attached(self):
        m = self.make_owner(self.user)
        self.assertEqual(self._run(self.user).membership, m)

    def test_non_member_is_none(self):
        self.assertIsNone(self._run(self.user).membership)

    def test_anonymous_is_none(self):
        self.assertIsNone(self._run(AnonymousUser()).membership)

    def test_no_company_is_none(self):
        req = self.rf.get('/dashboard/')
        req.user = self.user
        req.company = None
        self.mw(req)
        self.assertIsNone(req.membership)


class CanManageBranchTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='u', password='pass')
        self.a = Branch.objects.create(company=self.company, name='A', slug='a', address='X')
        self.b = Branch.objects.create(company=self.company, name='B', slug='b', address='Y')

    def test_owner_manages_any_branch(self):
        m = self.make_owner(self.user)
        self.assertTrue(can_manage_branch(m, self.a))
        self.assertTrue(can_manage_branch(m, self.b))

    def test_manager_only_assigned(self):
        m = self.make_manager(self.user, branches=[self.a])
        self.assertTrue(can_manage_branch(m, self.a))
        self.assertFalse(can_manage_branch(m, self.b))

    def test_none_membership_cannot(self):
        self.assertFalse(can_manage_branch(None, self.a))


class EnsureCanManageBranchTest(TenantTestCase):
    """Direct coverage of ensure_can_manage_branch, which wraps can_manage_branch
    with a superuser bypass and reads membership off the request object."""

    def setUp(self):
        super().setUp()
        self.rf = RequestFactory()
        self.branch = Branch.objects.create(
            company=self.company, name='Main', slug='main', address='Addr'
        )

    def _req(self, user, membership=None):
        req = self.rf.get('/dashboard/')
        req.user = user
        req.membership = membership
        return req

    def test_superuser_bypasses_membership_check(self):
        """Superuser with no membership should still return True."""
        su = User.objects.create_user(username='su', password='pass', is_superuser=True)
        req = self._req(su, membership=None)
        self.assertTrue(ensure_can_manage_branch(req, self.branch))

    def test_non_member_regular_user_is_false(self):
        """Regular user with no membership (None) must return False."""
        user = User.objects.create_user(username='nobody', password='pass')
        req = self._req(user, membership=None)
        self.assertFalse(ensure_can_manage_branch(req, self.branch))

    def test_manager_with_assigned_branch_is_true(self):
        """Manager membership that has the branch assigned must return True."""
        user = User.objects.create_user(username='mgr', password='pass')
        membership = self.make_manager(user, branches=[self.branch])
        req = self._req(user, membership=membership)
        self.assertTrue(ensure_can_manage_branch(req, self.branch))


class BranchScopeHttpTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.a = Branch.objects.create(company=self.company, name='A', slug='a', address='X')
        self.b = Branch.objects.create(company=self.company, name='B', slug='b', address='Y')
        self.manager = User.objects.create_user(username='mgr', password='pass')
        self.make_manager(self.manager, branches=[self.a])
        self.login_as(self.manager)

    def test_manager_can_open_assigned_branch(self):
        self.assertEqual(self.client.get('/dashboard/branch/a/').status_code, 200)

    def test_manager_403_on_unassigned_branch(self):
        self.assertEqual(self.client.get('/dashboard/branch/b/').status_code, 403)

    def test_owner_can_open_any_branch(self):
        owner_user = User.objects.create_user(username='own', password='pass')
        self.make_owner(owner_user)
        self.client.logout(); self.login_as(owner_user)
        self.assertEqual(self.client.get('/dashboard/branch/b/').status_code, 200)

    def test_manager_post_branch_category_add_unassigned_is_403(self):
        """Manager scoped to branch 'a' must get 403 POSTing category-add to branch 'b'."""
        cat = Category.objects.create(name='Drinks', slug='drinks', display_order=1)
        resp = self.client.post('/dashboard/branch/b/category/', {'category_id': cat.pk})
        self.assertEqual(resp.status_code, 403)

    def test_manager_post_branch_item_price_unassigned_is_403(self):
        """Manager scoped to branch 'a' must get 403 POSTing item price update to branch 'b'."""
        item = MenuItem.objects.create(name='Mango', slug='mango', price=380)
        resp = self.client.post(f'/dashboard/branch/b/item/{item.pk}/price/', {'price': '300'})
        self.assertEqual(resp.status_code, 403)


class HomeAggregationTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.a = Branch.objects.create(company=self.company, name='A', slug='a', address='X')
        self.b = Branch.objects.create(company=self.company, name='B', slug='b', address='Y')
        self.manager = User.objects.create_user(username='mgr', password='pass')
        self.make_manager(self.manager, branches=[self.a])
        self.login_as(self.manager)

    def test_manager_home_lists_only_assigned_branches(self):
        resp = self.client.get('/dashboard/')
        # home view stores branch under key 'obj' in branches_data dicts
        slugs = [d['obj'].slug for d in resp.context['branches_data']]
        self.assertEqual(set(slugs), {'a'})


class MemberManagementTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(company=self.company, name='Main', slug='main', address='X')
        self.owner = User.objects.create_user(username='owner', password='pass')
        self.make_owner(self.owner)
        self.login_as(self.owner)

    def test_owner_adds_manager_with_branch(self):
        resp = self.client.post('/dashboard/settings/members/add/', {
            'username': 'newmgr', 'email': 'm@x.com', 'password': 'pw',
            'role': 'manager', 'branches': [self.branch.pk]})
        self.assertRedirects(resp, '/dashboard/settings/', fetch_redirect_response=False)
        m = Membership.objects.get(user__username='newmgr', company=self.company)
        self.assertEqual(m.role, 'manager')
        self.assertEqual(list(m.branches.all()), [self.branch])

    def test_remove_member_deletes_membership_not_user(self):
        u = User.objects.create_user(username='temp', password='pass')
        m = self.make_manager(u)
        resp = self.client.post(f'/dashboard/settings/members/{m.pk}/delete/')
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertFalse(Membership.objects.filter(pk=m.pk).exists())
        self.assertTrue(User.objects.filter(username='temp').exists())

    def test_cannot_remove_last_owner(self):
        m = Membership.objects.get(user=self.owner, company=self.company)
        resp = self.client.post(f'/dashboard/settings/members/{m.pk}/delete/')
        self.assertFalse(resp.json()['ok'])
        self.assertTrue(Membership.objects.filter(pk=m.pk).exists())

    def test_cannot_demote_last_owner(self):
        m = Membership.objects.get(user=self.owner, company=self.company)
        resp = self.client.post(f'/dashboard/settings/members/{m.pk}/', {
            'username': 'owner', 'role': 'manager'})
        self.assertRedirects(resp, '/dashboard/settings/', fetch_redirect_response=False)
        m.refresh_from_db()
        self.assertTrue(m.is_owner)

    def test_manager_cannot_manage_members(self):
        mgr = User.objects.create_user(username='mgr', password='pass')
        self.make_manager(mgr)
        self.client.logout(); self.login_as(mgr)
        resp = self.client.post('/dashboard/settings/members/add/', {
            'username': 'x', 'password': 'pw', 'role': 'manager'})
        self.assertEqual(resp.status_code, 403)

    def test_add_member_refuses_existing_username_no_takeover(self):
        """Cross-tenant account takeover: posting an existing username must not reset
        that user's password or attach a membership to this company."""
        company_b = Company.objects.create(name='Juicery B', slug='juicery-b')
        boss_b = User.objects.create_user(username='bossB', password='original_pw')
        self.make_owner(boss_b, company=company_b)

        # Two companies now exist, so the Phase-1 shim (count==1) won't resolve the
        # tenant. Simulate the testco subdomain via HTTP_HOST so TenantMiddleware
        # resolves self.company regardless of DEBUG state.
        resp = self.client.post(
            '/dashboard/settings/members/add/',
            {'username': 'bossB', 'password': 'hacked', 'role': 'manager'},
            HTTP_HOST=f'{self.company_slug}.localhost')
        self.assertRedirects(resp, '/dashboard/settings/', fetch_redirect_response=False)

        # No membership created in company A for bossB
        self.assertFalse(
            Membership.objects.filter(user__username='bossB', company=self.company).exists())
        # Password was NOT reset
        boss_b.refresh_from_db()
        self.assertFalse(boss_b.check_password('hacked'))
        self.assertTrue(boss_b.check_password('original_pw'))

    def test_edit_modal_carries_assigned_branch_pks(self):
        """The settings page must embed the manager's current branch pks in the
        openEdit(...) call so that submitting the edit form preserves assignments."""
        mgr = User.objects.create_user(username='mgreditor', password='pass')
        self.make_manager(mgr, branches=[self.branch])

        resp = self.client.get('/dashboard/settings/')
        self.assertEqual(resp.status_code, 200)
        # The rendered HTML must contain the branch pk inside an openEdit(...) call
        branch_pk_str = f"'{self.branch.pk}'"
        self.assertContains(resp, 'openEdit(')
        self.assertContains(resp, branch_pk_str)


class LoginGateTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.member = User.objects.create_user(username='member', password='pass')
        self.make_owner(self.member)
        self.outsider = User.objects.create_user(username='outsider', password='pass')
        self.superu = User.objects.create_superuser(username='root', password='pass')

    def test_member_can_log_in(self):
        resp = self.client.post('/dashboard/login/', {'username': 'member', 'password': 'pass'})
        self.assertRedirects(resp, '/dashboard/', fetch_redirect_response=False)

    def test_non_member_rejected(self):
        resp = self.client.post('/dashboard/login/', {'username': 'outsider', 'password': 'pass'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Access denied')

    def test_superuser_allowed(self):
        resp = self.client.post('/dashboard/login/', {'username': 'root', 'password': 'pass'})
        self.assertRedirects(resp, '/dashboard/', fetch_redirect_response=False)

    def test_bad_password_rejected(self):
        resp = self.client.post('/dashboard/login/', {'username': 'member', 'password': 'wrong'})
        self.assertContains(resp, 'Access denied')


class CreateOwnerCommandTest(TenantTestCase):
    def test_creates_user_and_owner_membership(self):
        call_command('create_owner', self.company_slug, 'boss', '--password', 'pw')
        user = User.objects.get(username='boss')
        m = Membership.objects.get(user=user, company=self.company)
        self.assertTrue(m.is_owner)
        self.assertTrue(self.client.login(username='boss', password='pw'))

    def test_idempotent(self):
        call_command('create_owner', self.company_slug, 'boss', '--password', 'pw')
        call_command('create_owner', self.company_slug, 'boss', '--password', 'pw2')
        self.assertEqual(Membership.objects.filter(user__username='boss', company=self.company).count(), 1)

    def test_unknown_company_errors(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('create_owner', 'nope', 'boss', '--password', 'pw')
