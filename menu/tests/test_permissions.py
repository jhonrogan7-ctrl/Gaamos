from django.contrib.auth.models import User
from django.db import IntegrityError, transaction

from menu.models import Company, Branch, Membership
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
