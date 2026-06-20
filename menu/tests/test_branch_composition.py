from django.contrib.auth.models import User

from menu.models import (
    Branch, Category, SubCategory, MenuItem,
    BranchCategory, BranchSubCategory, BranchItemPlacement, BranchMenuItem,
)
from menu.tests.base import TenantTestCase


class BuilderEndpointTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        user = User.objects.create_user(username='mgr', password='pass', is_staff=True)
        self.make_owner(user)
        self.client.login(username='mgr', password='pass')
        self.b = Branch.objects.create(company=self.company, name='Main', slug='main', address='X')
        self.cat = Category.objects.create(name='Drinks', slug='drinks', display_order=1)
        self.sub = SubCategory.objects.create(category=self.cat, name='Smoothies')
        self.item = MenuItem.objects.create(name='Mango', slug='mango', price=380)

    def test_add_and_remove_category(self):
        r = self.client.post('/dashboard/branch/main/category/', {'category_id': self.cat.pk})
        self.assertEqual(r.status_code, 200)
        bc = BranchCategory.objects.get(branch=self.b, category=self.cat)
        r = self.client.post(f'/dashboard/branch/main/category/{bc.pk}/remove/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(BranchCategory.objects.filter(pk=bc.pk).exists())

    def test_remove_category_cascades_subs_and_placements(self):
        BranchCategory.objects.create(branch=self.b, category=self.cat)
        bsc = BranchSubCategory.objects.create(branch=self.b, sub_category=self.sub)
        BranchItemPlacement.objects.create(branch=self.b, menu_item=self.item,
                                           category=self.cat, sub_category=self.sub)
        bc = BranchCategory.objects.get(branch=self.b, category=self.cat)
        self.client.post(f'/dashboard/branch/main/category/{bc.pk}/remove/')
        self.assertFalse(BranchSubCategory.objects.filter(pk=bsc.pk).exists())
        self.assertFalse(BranchItemPlacement.objects.filter(branch=self.b, category=self.cat).exists())

    def test_add_subcategory(self):
        BranchCategory.objects.create(branch=self.b, category=self.cat)
        r = self.client.post('/dashboard/branch/main/subcategory/', {'sub_category_id': self.sub.pk})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(BranchSubCategory.objects.filter(branch=self.b, sub_category=self.sub).exists())

    def test_endpoints_require_login(self):
        self.client.logout()
        r = self.client.post('/dashboard/branch/main/category/', {'category_id': self.cat.pk})
        self.assertEqual(r.status_code, 302)

    def test_multiselect_add_placements(self):
        BranchCategory.objects.create(branch=self.b, category=self.cat)
        BranchSubCategory.objects.create(branch=self.b, sub_category=self.sub)
        item2 = MenuItem.objects.create(name='Berry', slug='berry', price=400)
        r = self.client.post('/dashboard/branch/main/placements/', {
            'item_ids': [self.item.pk, item2.pk],
            'category_id': self.cat.pk, 'sub_category_id': self.sub.pk})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            BranchItemPlacement.objects.filter(branch=self.b, sub_category=self.sub).count(), 2)

    def test_add_placements_is_idempotent(self):
        BranchCategory.objects.create(branch=self.b, category=self.cat)
        BranchSubCategory.objects.create(branch=self.b, sub_category=self.sub)
        for _ in range(2):
            self.client.post('/dashboard/branch/main/placements/', {
                'item_ids': [self.item.pk], 'category_id': self.cat.pk,
                'sub_category_id': self.sub.pk})
        self.assertEqual(BranchItemPlacement.objects.filter(branch=self.b).count(), 1)

    def test_remove_placement(self):
        pl = BranchItemPlacement.objects.create(branch=self.b, menu_item=self.item,
                                                category=self.cat, sub_category=self.sub)
        r = self.client.post(f'/dashboard/branch/main/placement/{pl.pk}/remove/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(BranchItemPlacement.objects.filter(pk=pl.pk).exists())

    def test_reorder_categories(self):
        c2 = Category.objects.create(name='Food', slug='food', display_order=2)
        a = BranchCategory.objects.create(branch=self.b, category=self.cat, display_order=0)
        bb = BranchCategory.objects.create(branch=self.b, category=c2, display_order=1)
        r = self.client.post('/dashboard/branch/main/reorder/',
                             {'level': 'category', 'ids': f'{bb.pk},{a.pk}'})
        self.assertEqual(r.status_code, 200)
        a.refresh_from_db(); bb.refresh_from_db()
        self.assertEqual((bb.display_order, a.display_order), (0, 1))


class CloneTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        user = User.objects.create_user(username='mgr', password='pass', is_staff=True)
        self.make_owner(user)
        self.client.login(username='mgr', password='pass')
        self.src = Branch.objects.create(company=self.company, name='Src', slug='src', address='X')
        self.dst = Branch.objects.create(company=self.company, name='Dst', slug='dst', address='Y')
        self.cat = Category.objects.create(name='Drinks', slug='drinks', display_order=1)
        self.sub = SubCategory.objects.create(category=self.cat, name='Smoothies')
        self.item = MenuItem.objects.create(name='Mango', slug='mango', price=380)
        BranchCategory.objects.create(branch=self.src, category=self.cat)
        BranchSubCategory.objects.create(branch=self.src, sub_category=self.sub)
        BranchItemPlacement.objects.create(branch=self.src, menu_item=self.item,
                                           category=self.cat, sub_category=self.sub)
        BranchMenuItem.objects.create(branch=self.src, menu_item=self.item, price_override=420)

    def test_full_clone(self):
        r = self.client.post('/dashboard/branch/dst/clone/', {'source': 'src'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(BranchCategory.objects.filter(branch=self.dst, category=self.cat).exists())
        self.assertTrue(BranchItemPlacement.objects.filter(branch=self.dst, menu_item=self.item).exists())
        self.assertEqual(
            BranchMenuItem.objects.get(branch=self.dst, menu_item=self.item).price_override, 420)

    def test_partial_clone_limits_to_categories(self):
        other = Category.objects.create(name='Food', slug='food', display_order=2)
        BranchCategory.objects.create(branch=self.src, category=other)
        self.client.post('/dashboard/branch/dst/clone/',
                         {'source': 'src', 'category_ids': str(self.cat.pk)})
        self.assertTrue(BranchCategory.objects.filter(branch=self.dst, category=self.cat).exists())
        self.assertFalse(BranchCategory.objects.filter(branch=self.dst, category=other).exists())


class GuestMenuTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.b = Branch.objects.create(company=self.company, name='Main', slug='main', address='X')
        self.cat = Category.objects.create(name='Drinks', slug='drinks', display_order=1)
        self.sub = SubCategory.objects.create(category=self.cat, name='Smoothies')
        self.sub2 = SubCategory.objects.create(category=self.cat, name='Summer')
        self.item = MenuItem.objects.create(name='Mango', slug='mango', price=380)
        BranchCategory.objects.create(branch=self.b, category=self.cat, display_order=0)
        BranchSubCategory.objects.create(branch=self.b, sub_category=self.sub, display_order=0)
        BranchSubCategory.objects.create(branch=self.b, sub_category=self.sub2, display_order=1)

    def _payload(self):
        resp = self.client.get('/?branch=main')
        self.assertEqual(resp.status_code, 200)
        return resp.context['payload']

    def test_only_placed_categories_render(self):
        Category.objects.create(name='Food', slug='food', display_order=2)
        p = self._payload()
        self.assertEqual([c['id'] for c in p['categories']], ['drinks'])

    def test_placed_item_renders_with_effective_price(self):
        BranchItemPlacement.objects.create(branch=self.b, menu_item=self.item,
                                           category=self.cat, sub_category=self.sub)
        BranchMenuItem.objects.create(branch=self.b, menu_item=self.item, price_override=420)
        dishes = self._payload()['dishes']
        self.assertEqual(len(dishes), 1)
        self.assertEqual(dishes[0]['price'], 420)
        self.assertEqual(dishes[0]['sub'], 'Smoothies')

    def test_multiple_placements_render_twice(self):
        BranchItemPlacement.objects.create(branch=self.b, menu_item=self.item,
                                           category=self.cat, sub_category=self.sub)
        BranchItemPlacement.objects.create(branch=self.b, menu_item=self.item,
                                           category=self.cat, sub_category=self.sub2)
        subs = sorted(d['sub'] for d in self._payload()['dishes'])
        self.assertEqual(subs, ['Smoothies', 'Summer'])


class CompositionModelTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.b = Branch.objects.create(company=self.company, name='Main', slug='main', address='X')
        self.cat = Category.objects.create(name='Drinks', slug='drinks', display_order=1)
        self.sub = SubCategory.objects.create(category=self.cat, name='Smoothies')
        self.item = MenuItem.objects.create(name='Mango', slug='mango', price=380)

    def test_placement_presence_and_order(self):
        BranchCategory.objects.create(branch=self.b, category=self.cat, display_order=0)
        BranchSubCategory.objects.create(branch=self.b, sub_category=self.sub, display_order=0)
        p = BranchItemPlacement.objects.create(
            branch=self.b, menu_item=self.item, category=self.cat,
            sub_category=self.sub, display_order=0)
        self.assertEqual(self.b.placements.count(), 1)
        self.assertEqual(p.sub_category, self.sub)

    def test_multiple_placements_of_one_item(self):
        sub2 = SubCategory.objects.create(category=self.cat, name='Summer')
        BranchItemPlacement.objects.create(
            branch=self.b, menu_item=self.item, category=self.cat, sub_category=self.sub)
        BranchItemPlacement.objects.create(
            branch=self.b, menu_item=self.item, category=self.cat, sub_category=sub2)
        self.assertEqual(
            BranchItemPlacement.objects.filter(branch=self.b, menu_item=self.item).count(), 2)

    def test_price_override_shared_per_branch_item(self):
        bmi = BranchMenuItem.objects.create(branch=self.b, menu_item=self.item, price_override=420)
        self.assertEqual(bmi.effective_price, 420)
        bmi.price_override = None
        self.assertEqual(bmi.effective_price, 380)
