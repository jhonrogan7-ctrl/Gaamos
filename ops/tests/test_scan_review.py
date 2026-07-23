from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase

from menu.models import Item, MenuScan

APEX = settings.BASE_DOMAIN

MENU = {"categories": [{"name": "Hot Drinks", "items": [
    {"name": "Black Tea", "description": "hot milk tea", "price": 50}]}]}


def _emb(vec):
    return lambda text: vec


class ScanReviewTests(TestCase):
    def setUp(self):
        self.apex = {'HTTP_HOST': APEX}
        self.boss = User.objects.create_superuser('boss', 'b@x.io', 'pw-boss-1')
        self.scan = MenuScan.objects.create(source_cafe='Cafe', status='extracted',
                                            raw_extraction=MENU, file='scans/x.pdf')
        self.client.force_login(self.boss)

    def test_review_requires_superuser(self):
        self.client.logout()
        self.assertEqual(
            self.client.get(f'/platform/scans/{self.scan.pk}/review/', **self.apex).status_code, 302)

    def test_review_lists_proposed_items(self):
        body = self.client.get(f'/platform/scans/{self.scan.pk}/review/', **self.apex).content.decode()
        self.assertIn('Black Tea', body)
        self.assertIn('Hot Drinks', body)

    def test_approve_creates_item_with_embedding(self):
        with patch('menu.pipeline.embed.embed', _emb([0.2] * 768)):
            resp = self.client.post(f'/platform/scans/{self.scan.pk}/approve/',
                                    {'name': 'Black Tea', 'description': 'hot milk tea',
                                     'category': 'Hot Drinks', 'reference_price': '50'},
                                    **self.apex)
        self.assertEqual(resp.status_code, 200)
        item = Item.objects.get(name='Black Tea')
        self.assertEqual(item.category, 'Hot Drinks')
        self.assertEqual(item.reference_price, 50)
        self.assertEqual(list(item.embedding), [0.2] * 768)
        self.assertEqual(item.source_scan_id, self.scan.pk)

    def test_approve_links_to_existing_above_threshold(self):
        existing = Item.objects.create(name='Black Tea', category='Hot Drinks',
                                       embedding=[1.0] + [0.0] * 767)
        # query embed identical to existing → similarity 1.0 ≥ threshold → link, no new row
        with patch('menu.pipeline.embed.embed', _emb([1.0] + [0.0] * 767)):
            resp = self.client.post(f'/platform/scans/{self.scan.pk}/approve/',
                                    {'name': 'Black Tea', 'category': 'Hot Drinks',
                                     'link_to': str(existing.pk)}, **self.apex)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Item.objects.filter(name='Black Tea').count(), 1)  # no duplicate

    def test_approve_bad_price_is_400(self):
        resp = self.client.post(f'/platform/scans/{self.scan.pk}/approve/',
                                {'name': 'Black Tea', 'description': 'hot milk tea',
                                 'category': 'Hot Drinks', 'reference_price': 'abc'},
                                **self.apex)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Item.objects.filter(name='Black Tea').exists())

    def test_approve_marks_scan_imported(self):
        with patch('menu.pipeline.embed.embed', _emb([0.2] * 768)):
            resp = self.client.post(f'/platform/scans/{self.scan.pk}/approve/',
                                    {'name': 'Black Tea', 'description': 'hot milk tea',
                                     'category': 'Hot Drinks', 'reference_price': '50'},
                                    **self.apex)
        self.assertEqual(resp.status_code, 200)
        self.scan.refresh_from_db()
        self.assertEqual(self.scan.status, 'imported')
