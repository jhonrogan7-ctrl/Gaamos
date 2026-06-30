from django.contrib.auth import get_user_model
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
