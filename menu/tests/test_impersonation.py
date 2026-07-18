from unittest import mock

from django.contrib.auth.models import User

from menu.impersonation import make_token, resolve_token
from menu.models import Company
from menu.tests.base import TenantTestCase


class TokenHelperTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser('boss', 'b@x.io', 'pw')

    def test_round_trip_resolves_admin(self):
        token = make_token(self.admin, self.company)
        self.assertEqual(resolve_token(token, self.company), self.admin)

    def test_token_is_single_use(self):
        token = make_token(self.admin, self.company)
        self.assertEqual(resolve_token(token, self.company), self.admin)
        self.assertIsNone(resolve_token(token, self.company))

    def test_wrong_company_rejected(self):
        other = Company.objects.create(name='Other Co', slug='otherco')
        token = make_token(self.admin, other)
        self.assertIsNone(resolve_token(token, self.company))
        # and the nonce was NOT burned by the failed attempt on the wrong host
        self.assertEqual(resolve_token(token, other), self.admin)

    def test_none_company_rejected(self):
        token = make_token(self.admin, self.company)
        self.assertIsNone(resolve_token(token, None))

    def test_tampered_token_rejected(self):
        token = make_token(self.admin, self.company)
        self.assertIsNone(resolve_token(token[:-2] + 'zz', self.company))

    def test_garbage_token_rejected(self):
        self.assertIsNone(resolve_token('not-a-token', self.company))
        self.assertIsNone(resolve_token('', self.company))

    def test_expired_token_rejected(self):
        token = make_token(self.admin, self.company)
        with mock.patch('menu.impersonation.MAX_AGE', -1):
            self.assertIsNone(resolve_token(token, self.company))

    def test_non_superuser_target_rejected(self):
        plain = User.objects.create_user('plain', 'p@x.io', 'pw')
        token = make_token(plain, self.company)
        self.assertIsNone(resolve_token(token, self.company))

    def test_inactive_superuser_rejected(self):
        self.admin.is_active = False
        self.admin.save(update_fields=['is_active'])
        token = make_token(self.admin, self.company)
        self.assertIsNone(resolve_token(token, self.company))
