from django.contrib.auth.models import User

from menu.models import (
    Branch, Category, SubCategory, MenuItem, BranchMenuItem,
    BranchCategory, BranchItemPlacement,
)
from menu.tests.base import TenantTestCase


class DashboardAuthTest(TenantTestCase):
    def test_dashboard_redirects_anonymous(self):
        response = self.client.get('/dashboard/')
        self.assertRedirects(response, '/dashboard/login/?next=/dashboard/', fetch_redirect_response=False)

    def test_login_page_loads(self):
        response = self.client.get('/dashboard/login/')
        self.assertEqual(response.status_code, 200)

    def test_staff_user_can_access_dashboard(self):
        user = User.objects.create_user(username='mgr', password='pass', is_staff=True)
        self.make_owner(user)
        self.client.login(username='mgr', password='pass')
        response = self.client.get('/dashboard/')
        self.assertEqual(response.status_code, 200)

    def test_non_staff_login_rejected(self):
        User.objects.create_user(username='guest', password='pass', is_staff=False)
        response = self.client.post('/dashboard/login/', {'username': 'guest', 'password': 'pass'})
        self.assertEqual(response.status_code, 200)  # re-renders login with error
        self.assertContains(response, 'Access denied')

    def test_mutation_endpoint_redirects_anonymous_not_405(self):
        """@login_required must be outermost so anonymous GETs redirect, not 405."""
        response = self.client.get('/dashboard/items/1/delete/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/dashboard/login/', response['Location'])


class DashboardHomeTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='mgr2', password='pass', is_staff=True)
        self.make_owner(self.user)
        self.client.login(username='mgr2', password='pass')
        self.branch = Branch.objects.create(company=self.company, name='Main', slug='main', address='Lakeside')
        self.cat = Category.objects.create(name='Brunch', slug='brunch', display_order=1)
        MenuItem.objects.create(name='Pizza 1', slug='pizza-1', price=500)
        self.item2 = MenuItem.objects.create(name='Pizza 2', slug='pizza-2', price=400)

    def test_home_shows_branch_cards(self):
        response = self.client.get('/dashboard/')
        self.assertEqual(response.status_code, 200)
        branches_data = response.context['branches_data']
        self.assertEqual(len(branches_data), 1)
        self.assertEqual(branches_data[0]['active_count'], 0)  # no placements yet
        self.assertEqual(branches_data[0]['total_count'], 2)   # two item templates exist
        self.assertContains(response, 'Main')

    def test_home_active_count_reflects_placements(self):
        BranchCategory.objects.create(branch=self.branch, category=self.cat)
        BranchItemPlacement.objects.create(branch=self.branch, menu_item=self.item2, category=self.cat)
        response = self.client.get('/dashboard/')
        self.assertEqual(response.context['branches_data'][0]['active_count'], 1)


class ItemsListTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='mgr3', password='pass', is_staff=True)
        self.make_owner(self.user)
        self.client.login(username='mgr3', password='pass')
        self.item = MenuItem.objects.create(name='Margherita', slug='margherita', price=500)

    def test_items_list_returns_200(self):
        response = self.client.get('/dashboard/items/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Margherita')

    def test_items_list_search(self):
        MenuItem.objects.create(name='Pepperoni', slug='pepperoni', price=600)
        response = self.client.get('/dashboard/items/?q=marg')
        self.assertContains(response, 'Margherita')
        self.assertNotContains(response, 'Pepperoni')


class ItemEditTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='mgr4', password='pass', is_staff=True)
        self.make_owner(self.user)
        self.client.login(username='mgr4', password='pass')

    def test_add_item_page_loads(self):
        response = self.client.get('/dashboard/items/add/')
        self.assertEqual(response.status_code, 200)

    def test_create_item_via_post(self):
        response = self.client.post('/dashboard/items/add/', {
            'name': 'New Pizza',
            'price': 600,
            'description': 'Tasty',
            'dietary_tags': ['VEG'],
        })
        self.assertEqual(MenuItem.objects.filter(name='New Pizza').count(), 1)
        self.assertRedirects(response, '/dashboard/items/', fetch_redirect_response=False)

    def test_delete_item(self):
        item = MenuItem.objects.create(name='Del Me', slug='del-me', price=100)
        response = self.client.post(f'/dashboard/items/{item.pk}/delete/')
        self.assertEqual(MenuItem.objects.filter(pk=item.pk).count(), 0)
        self.assertRedirects(response, '/dashboard/items/', fetch_redirect_response=False)


class CategoriesTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='mgr5', password='pass', is_staff=True)
        self.make_owner(self.user)
        self.client.login(username='mgr5', password='pass')
        self.branch = Branch.objects.create(company=self.company, name='Main', slug='main', address='X')
        self.cat = Category.objects.create(name='Brunch', slug='brunch', display_order=1)
        self.sub = SubCategory.objects.create(category=self.cat, name='Pizza', display_order=1)

    def test_categories_page_loads(self):
        response = self.client.get('/dashboard/categories/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Brunch')

    def test_add_category(self):
        response = self.client.post('/dashboard/categories/add/', {
            'name': 'Desserts', 'icon_key': '🍰', 'hours_note': ''
        })
        self.assertEqual(Category.objects.filter(name='Desserts').count(), 1)
        self.assertRedirects(response, '/dashboard/categories/', fetch_redirect_response=False)

    def test_add_subcategory(self):
        response = self.client.post('/dashboard/subcategories/add/', {
            'category': self.cat.pk, 'name': 'Waffles', 'icon_key': '🧇'
        })
        self.assertEqual(SubCategory.objects.filter(name='Waffles').count(), 1)

    def test_delete_subcategory_in_use_blocked(self):
        import json
        item = MenuItem.objects.create(name='Pizza 1', slug='pizza-1-cat', price=500)
        BranchItemPlacement.objects.create(
            branch=self.branch, menu_item=item, category=self.cat, sub_category=self.sub)
        response = self.client.post(f'/dashboard/subcategories/{self.sub.pk}/delete/')
        data = json.loads(response.content)
        self.assertFalse(data['ok'])
        self.assertIn('branch', data['error'].lower())

    def test_delete_unused_subcategory(self):
        import json
        empty_sub = SubCategory.objects.create(category=self.cat, name='Empty', display_order=2)
        response = self.client.post(f'/dashboard/subcategories/{empty_sub.pk}/delete/')
        data = json.loads(response.content)
        self.assertTrue(data['ok'])
        self.assertEqual(SubCategory.objects.filter(pk=empty_sub.pk).count(), 0)

    def test_delete_category_in_use_blocked(self):
        import json
        item = MenuItem.objects.create(name='Item', slug='item-x', price=100)
        BranchItemPlacement.objects.create(branch=self.branch, menu_item=item, category=self.cat)
        response = self.client.post(f'/dashboard/categories/{self.cat.pk}/delete/')
        data = json.loads(response.content)
        self.assertFalse(data['ok'])


class QRCodesTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='mgr6', password='pass', is_staff=True)
        self.make_owner(self.user)
        self.client.login(username='mgr6', password='pass')
        self.branch = Branch.objects.create(
            company=self.company, name='Main', slug='main', address='Lakeside'
        )

    def test_qr_page_loads(self):
        response = self.client.get('/dashboard/qr/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Main')

    def test_generate_qr(self):
        response = self.client.post(f'/dashboard/qr/{self.branch.pk}/generate/')
        self.assertRedirects(response, '/dashboard/qr/', fetch_redirect_response=False)
        self.branch.refresh_from_db()
        self.assertTrue(self.branch.qr_image != '')
        self.assertTrue(self.branch.qr_image.startswith('qr/'))


class SettingsTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='mgr7', password='pass', is_staff=True)
        self.make_owner(self.user)
        self.client.login(username='mgr7', password='pass')

    def test_settings_page_loads(self):
        response = self.client.get('/dashboard/settings/')
        self.assertEqual(response.status_code, 200)

    def test_update_restaurant(self):
        response = self.client.post('/dashboard/settings/restaurant/', {
            'name': 'New Name', 'tagline': 'New Tag', 'phone': '123', 'email': 'a@b.com',
            'instagram': '', 'facebook': '', 'tiktok': '',
        })
        self.company.refresh_from_db()
        self.assertEqual(self.company.name, 'New Name')
        self.assertRedirects(response, '/dashboard/settings/', fetch_redirect_response=False)

    def test_add_branch(self):
        response = self.client.post('/dashboard/branches/add/', {
            'name': 'City Branch', 'address': 'Newroad', 'tag': 'NEW',
        })
        self.assertEqual(Branch.objects.filter(name='City Branch').count(), 1)
        self.assertRedirects(response, '/dashboard/branches/',
                             fetch_redirect_response=False)


class BranchManageTest(TenantTestCase):
    """Branch Add/Edit lives on the Branches screen (owner-only), incl. theme override."""

    def setUp(self):
        super().setUp()
        self.owner = User.objects.create_user(username='own1', password='pass')
        self.make_owner(self.owner)
        self.branch = Branch.objects.create(
            company=self.company, name='Main', slug='main', address='Lakeside')

    def test_add_saves_theme_override(self):
        self.client.login(username='own1', password='pass')
        self.client.post('/dashboard/branches/add/', {
            'name': 'Patan', 'address': 'Mangal Bazaar', 'tag': '', 'menu_theme': 'berry'})
        self.assertEqual(Branch.objects.get(name='Patan').menu_theme, 'berry')

    def test_edit_can_reset_to_company_default(self):
        self.branch.menu_theme = 'juice'
        self.branch.save()
        self.client.login(username='own1', password='pass')
        self.client.post(f'/dashboard/branches/{self.branch.pk}/edit/', {
            'name': 'Main', 'address': 'Lakeside', 'tag': '', 'menu_theme': ''})
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.menu_theme, '')

    def test_invalid_theme_ignored(self):
        self.client.login(username='own1', password='pass')
        self.client.post('/dashboard/branches/add/', {
            'name': 'Bhaktapur', 'address': 'Durbar', 'tag': '', 'menu_theme': 'neon'})
        self.assertEqual(Branch.objects.get(name='Bhaktapur').menu_theme, '')

    def test_manager_cannot_add_or_edit(self):
        mgr = User.objects.create_user(username='mgr1', password='pass')
        self.make_manager(mgr, branches=[self.branch])
        self.client.login(username='mgr1', password='pass')
        r1 = self.client.post('/dashboard/branches/add/', {'name': 'Rogue', 'address': ''})
        r2 = self.client.post(f'/dashboard/branches/{self.branch.pk}/edit/',
                              {'name': 'Hacked', 'address': ''})
        self.assertEqual(r1.status_code, 403)
        self.assertEqual(r2.status_code, 403)
        self.assertFalse(Branch.objects.filter(name='Rogue').exists())
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.name, 'Main')

    def test_branches_page_has_sheet_for_owner_only(self):
        self.client.login(username='own1', password='pass')
        body = self.client.get('/dashboard/branches/').content.decode()
        self.assertIn('sheet-backdrop', body)
        self.assertIn('branchManager()', body)
        self.assertIn('Company default', body)      # theme picker inherit option
        self.assertIn('@click="openAdd()"', body)   # add card opens the sheet…
        self.assertNotIn('href="/dashboard/settings/" class="bcard add"', body)  # …old settings-link card is gone
        mgr = User.objects.create_user(username='mgr2', password='pass')
        self.make_manager(mgr, branches=[self.branch])
        self.client.login(username='mgr2', password='pass')
        body = self.client.get('/dashboard/branches/').content.decode()
        self.assertNotIn('branchManager()', body)


class BranchItemsTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='branchmgr', password='pass', is_staff=True)
        self.make_owner(self.user)
        self.client.login(username='branchmgr', password='pass')
        self.branch = Branch.objects.create(
            company=self.company, name='Main', slug='main', address='Lakeside'
        )
        self.cat = Category.objects.create(name='Brunch', slug='brunch', display_order=1)
        self.item = MenuItem.objects.create(name='Dosa', slug='dosa', price=180)

    def test_branch_items_view_loads(self):
        # 'Dosa' is in the library payload even before it is placed.
        response = self.client.get('/dashboard/branch/main/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dosa')

    def test_branch_items_view_requires_login(self):
        self.client.logout()
        response = self.client.get('/dashboard/branch/main/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/dashboard/login/', response['Location'])

    def test_branch_items_view_404_for_unknown_slug(self):
        response = self.client.get('/dashboard/branch/nonexistent/')
        self.assertEqual(response.status_code, 404)

    def test_price_endpoint_sets_override(self):
        import json
        BranchMenuItem.objects.create(branch=self.branch, menu_item=self.item)
        response = self.client.post(
            f'/dashboard/branch/main/item/{self.item.pk}/price/',
            {'price': '350'}
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['price_override'], 350)
        self.assertEqual(BranchMenuItem.objects.get(branch=self.branch, menu_item=self.item).price_override, 350)

    def test_price_endpoint_clears_override(self):
        import json
        BranchMenuItem.objects.create(branch=self.branch, menu_item=self.item, price_override=350)
        response = self.client.post(
            f'/dashboard/branch/main/item/{self.item.pk}/price/',
            {'price': ''}
        )
        data = json.loads(response.content)
        self.assertIsNone(data['price_override'])
        self.assertIsNone(BranchMenuItem.objects.get(branch=self.branch, menu_item=self.item).price_override)


class ManagerRestrictionsTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(company=self.company, name='Main', slug='main', address='X')
        self.manager = User.objects.create_user(username='mgr', password='pass')
        self.make_manager(self.manager, branches=[self.branch])
        self.login_as(self.manager)

    def test_manager_blocked_from_items_list(self):
        self.assertEqual(self.client.get('/dashboard/items/').status_code, 403)

    def test_manager_blocked_from_categories(self):
        self.assertEqual(self.client.get('/dashboard/categories/').status_code, 403)

    def test_manager_blocked_from_settings(self):
        self.assertEqual(self.client.get('/dashboard/settings/').status_code, 403)

    def test_manager_can_load_home(self):
        self.assertEqual(self.client.get('/dashboard/').status_code, 200)

    def test_manager_blocked_from_category_delete(self):
        cat = Category.objects.create(name='X', slug='x', display_order=1)
        resp = self.client.post(f'/dashboard/categories/{cat.pk}/delete/')
        self.assertEqual(resp.status_code, 403)
