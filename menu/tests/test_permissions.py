from django.contrib.auth.models import AnonymousUser, User
from django.db import IntegrityError, transaction
from django.test import RequestFactory

from menu.middleware import MembershipMiddleware
from menu.models import Branch, Company, Membership
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
        self.assertEqual(slugs, ['a'])


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
