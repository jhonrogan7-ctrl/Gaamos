import json
import re
from django.test import TestCase, override_settings
from menu.tests.base import TenantTestCase
from menu.models import (
    Branch, Category, Company, MenuItem, BranchMenuItem,
    BranchCategory, BranchItemPlacement,
)


def place(branch, item, category, sub_category=None, price_override=None):
    """Test helper: put an item on a branch's menu (the composition way)."""
    BranchCategory.objects.get_or_create(branch=branch, category=category)
    BranchItemPlacement.objects.create(
        branch=branch, menu_item=item, category=category, sub_category=sub_category)
    if price_override is not None:
        BranchMenuItem.objects.update_or_create(
            branch=branch, menu_item=item, defaults={'price_override': price_override})


class MenuViewTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        # Set fields on the company TenantTestCase created
        self.company.name = "The Juicery Cafe"
        self.company.tagline = "Taste True Wellness"
        self.company.phone = "+977-9823781787"
        self.company.email = "info@thejuicerycafe.com.np"
        self.company.save()
        Category.objects.create(name="Brunch", slug="brunch", icon_key="brunch", display_order=1)

    def test_view_returns_200(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

    def test_payload_json_script_present(self):
        response = self.client.get('/')
        self.assertIn(b'id="menu-data"', response.content)

    def test_payload_has_required_keys(self):
        response = self.client.get('/')
        match = re.search(
            r'<script id="menu-data" type="application/json">(.*?)</script>',
            response.content.decode(), re.DOTALL,
        )
        self.assertIsNotNone(match)
        payload = json.loads(match.group(1))
        self.assertIn('restaurant', payload)
        self.assertIn('branches', payload)
        self.assertIn('categories', payload)
        self.assertIn('dishes', payload)

    def test_payload_restaurant_name(self):
        response = self.client.get('/')
        match = re.search(
            r'<script id="menu-data" type="application/json">(.*?)</script>',
            response.content.decode(), re.DOTALL,
        )
        payload = json.loads(match.group(1))
        self.assertEqual(payload['restaurant']['name'], "The Juicery Cafe")


class GuestMenuUpdatesTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.branch_main = Branch.objects.create(
            company=self.company, name='Main', slug='main', address='Lakeside'
        )
        self.branch_city = Branch.objects.create(
            company=self.company, name='City', slug='city', address='Newroad'
        )
        self.cat = Category.objects.create(name='Brunch', slug='brunch', display_order=1)
        self.placed_item = MenuItem.objects.create(name='Active', slug='active-item', price=100)
        self.unplaced_item = MenuItem.objects.create(name='Hidden', slug='hidden-item', price=200)
        # Placed item appears on the main branch; unplaced item does not.
        place(self.branch_main, self.placed_item, self.cat)

    def test_unplaced_items_excluded_from_dishes(self):
        response = self.client.get('/?branch=main')
        match = re.search(r'<script id="menu-data" type="application/json">(.*?)</script>',
                          response.content.decode(), re.DOTALL)
        payload = json.loads(match.group(1))
        names = [d['name'] for d in payload['dishes']]
        self.assertIn('Active', names)
        self.assertNotIn('Hidden', names)

    def test_branch_slug_param_sets_selected_branch(self):
        response = self.client.get('/?branch=city')
        match = re.search(r'<script id="menu-data" type="application/json">(.*?)</script>',
                          response.content.decode(), re.DOTALL)
        payload = json.loads(match.group(1))
        self.assertEqual(payload['selected_branch'], 'city')


class GuestMenuBranchFilterTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.branch_a = Branch.objects.create(
            company=self.company, name='Branch A', slug='branch-a', address='Addr A'
        )
        self.branch_b = Branch.objects.create(
            company=self.company, name='Branch B', slug='branch-b', address='Addr B'
        )
        self.cat = Category.objects.create(name='Food', slug='food', display_order=1)
        self.item_a = MenuItem.objects.create(name='Item A', slug='item-a', price=100)
        self.item_b = MenuItem.objects.create(name='Item B', slug='item-b', price=200)
        self.item_price = MenuItem.objects.create(name='Priced', slug='priced', price=300)
        # Branch A has item_a and item_price (with override)
        place(self.branch_a, self.item_a, self.cat)
        place(self.branch_a, self.item_price, self.cat, price_override=999)
        # Branch B has only item_b
        place(self.branch_b, self.item_b, self.cat)

    def _get_dishes(self, branch_slug=''):
        url = f'/?branch={branch_slug}' if branch_slug else '/'
        response = self.client.get(url)
        match = re.search(r'<script id="menu-data" type="application/json">(.*?)</script>',
                          response.content.decode(), re.DOTALL)
        return json.loads(match.group(1))['dishes']

    def test_branch_a_shows_only_its_items(self):
        dishes = self._get_dishes('branch-a')
        names = [d['name'] for d in dishes]
        self.assertIn('Item A', names)
        self.assertNotIn('Item B', names)

    def test_branch_b_shows_only_its_items(self):
        dishes = self._get_dishes('branch-b')
        names = [d['name'] for d in dishes]
        self.assertIn('Item B', names)
        self.assertNotIn('Item A', names)

    def test_price_override_used_when_set(self):
        dishes = self._get_dishes('branch-a')
        priced = next(d for d in dishes if d['name'] == 'Priced')
        self.assertEqual(priced['price'], 999)

    def test_template_price_used_when_no_override(self):
        dishes = self._get_dishes('branch-a')
        item_a = next(d for d in dishes if d['name'] == 'Item A')
        self.assertEqual(item_a['price'], 100)

    def test_unplaced_item_excluded(self):
        # An item template that exists globally but is not placed never renders.
        MenuItem.objects.create(name='Unplaced', slug='unplaced', price=50)
        dishes = self._get_dishes('branch-a')
        names = [d['name'] for d in dishes]
        self.assertNotIn('Unplaced', names)

    def test_fallback_to_first_branch_when_no_slug(self):
        # First branch by pk is branch_a — it has item_a
        dishes = self._get_dishes('')
        names = [d['name'] for d in dishes]
        self.assertIn('Item A', names)
        self.assertNotIn('Item B', names)

    def test_unknown_branch_slug_falls_back_to_first_branch(self):
        dishes = self._get_dishes('does-not-exist')
        names = [d['name'] for d in dishes]
        self.assertIn('Item A', names)


class PlaceOrderTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.cat = Category.objects.create(name="Brunch", slug="brunch", icon_key="brunch", display_order=1)
        self.branch = Branch.objects.create(company=self.company, name="Main", slug="main")
        self.item_a = MenuItem.objects.create(
            name="Item A", slug="item-a", price=200, order_count=0,
        )
        self.item_b = MenuItem.objects.create(
            name="Item B", slug="item-b", price=150, order_count=5,
        )

    def test_place_order_increments_order_count_by_qty(self):
        resp = self.client.post(
            '/api/order/',
            data=json.dumps({'branch': 'main', 'items': [
                {'id': self.item_a.id, 'qty': 3},
                {'id': self.item_b.id, 'qty': 2},
            ]}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get('ok'))
        self.item_a.refresh_from_db()
        self.item_b.refresh_from_db()
        self.assertEqual(self.item_a.order_count, 3)
        self.assertEqual(self.item_b.order_count, 7)

    def test_place_order_empty_items_rejected(self):
        # Spec 3: an order needs at least one valid item — empty is a 400, no-op.
        resp = self.client.post(
            '/api/order/', data=json.dumps({'branch': 'main', 'items': []}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.item_b.refresh_from_db()
        self.assertEqual(self.item_b.order_count, 5)

    def test_place_order_malformed_body_does_not_500(self):
        resp = self.client.post('/api/order/', data='not json', content_type='application/json')
        self.assertIn(resp.status_code, (200, 400))

    def test_place_order_all_bad_items_rejected(self):
        # Unknown id + non-positive qty are skipped; with no valid lines → 400, no-op.
        resp = self.client.post(
            '/api/order/',
            data=json.dumps({'branch': 'main', 'items': [
                {'id': 999999, 'qty': 2},
                {'id': self.item_a.id, 'qty': 0},
                {'id': self.item_a.id, 'qty': -4},
            ]}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.item_a.refresh_from_db()
        self.assertEqual(self.item_a.order_count, 0)


@override_settings(BASE_DOMAIN='zxyn.online', ALLOWED_HOSTS=['.zxyn.online', 'testserver'])
class PlaceOrderTenantIsolationTest(TestCase):
    """A guest request resolved to company A must not be able to bump company B's
    item order_count, even by guessing B's item pk."""

    def setUp(self):
        self.a = Company.objects.create(name='A Co', slug='aco', status='active')
        self.b = Company.objects.create(name='B Co', slug='bco', status='active')
        self.item_b = MenuItem.all_objects.create(
            company=self.b, name='Secret', slug='secret', price=100)

    def test_order_from_company_a_cannot_touch_company_b_item(self):
        resp = self.client.post(
            '/api/order/',
            data=json.dumps({'items': [{'id': self.item_b.pk, 'qty': 5}]}),
            content_type='application/json',
            HTTP_HOST='aco.zxyn.online',   # resolves to company A
        )
        # B's item is outside A's tenant scope → filtered out → no valid items → 400.
        self.assertEqual(resp.status_code, 400)
        self.item_b.refresh_from_db()
        self.assertEqual(self.item_b.order_count, 0)  # B's item untouched by an A request


class MenuLayoutTest(TenantTestCase):
    def _payload(self, url='/'):
        response = self.client.get(url)
        match = re.search(
            r'<script id="menu-data" type="application/json">(.*?)</script>',
            response.content.decode(), re.DOTALL)
        return json.loads(match.group(1))

    def test_payload_carries_company_layout(self):
        self.company.menu_layout = 'tabs'
        self.company.save()
        self.assertEqual(self._payload()['layout'], 'tabs')

    def test_default_layout_baseline(self):
        self.assertEqual(self._payload()['layout'], 'baseline')

    def test_preview_param_overrides(self):
        self.assertEqual(self._payload('/?layout=iconrail')['layout'], 'iconrail')

    def test_invalid_param_falls_back_to_company(self):
        self.assertEqual(self._payload('/?layout=bogus')['layout'], 'baseline')


class GuestThemeTest(TenantTestCase):
    def test_guest_html_carries_inline_theme_tokens(self):
        # The company default is eco; the resolved theme's full token set is
        # emitted inline on the guest <html>.
        resp = self.client.get('/')
        body = resp.content.decode()
        self.assertIn('--brand:#2D6A4F', body)
        self.assertIn('--paper:#EFEAD8', body)
        self.assertIn('--grad:linear-gradient(135deg,#A3B18A,#2D6A4F)', body)

    def test_menu_uses_company_theme(self):
        self.company.menu_theme = 'cozy'
        self.company.save()
        resp = self.client.get('/')
        self.assertContains(resp, 'data-theme="cozy"')
        self.assertContains(resp, '--brand:#8A6423')

    def test_theme_query_param_previews(self):
        resp = self.client.get('/?theme=fastfood')
        self.assertContains(resp, 'data-theme="fastfood"')
        self.assertContains(resp, '--brand:#E53E3E')

    def test_invalid_theme_falls_back_to_company(self):
        resp = self.client.get('/?theme=neon')
        self.assertContains(resp, 'data-theme="eco"')

    def test_legacy_stored_slug_falls_back_to_default(self):
        # Rows can hold pre-migration slugs; resolution must degrade to eco.
        Company.objects.filter(pk=self.company.pk).update(menu_theme='saffron')
        resp = self.client.get('/')
        self.assertContains(resp, 'data-theme="eco"')
        self.assertContains(resp, '--brand:#2D6A4F')

    def test_branch_theme_overrides_company_default(self):
        self.company.menu_theme = 'cozy'
        self.company.save()
        Branch.objects.create(company=self.company, name='Main', slug='main',
                              address='X', menu_theme='herbal')
        resp = self.client.get('/')
        self.assertContains(resp, 'data-theme="herbal"')

    def test_branch_without_theme_inherits_company_default(self):
        self.company.menu_theme = 'cozy'
        self.company.save()
        Branch.objects.create(company=self.company, name='Main', slug='main', address='X')
        resp = self.client.get('/')
        self.assertContains(resp, 'data-theme="cozy"')

    def test_preview_param_beats_branch_theme(self):
        Branch.objects.create(company=self.company, name='Main', slug='main',
                              address='X', menu_theme='herbal')
        resp = self.client.get('/?theme=eco')
        self.assertContains(resp, 'data-theme="eco"')
