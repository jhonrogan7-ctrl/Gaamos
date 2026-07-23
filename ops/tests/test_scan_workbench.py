from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase

from menu.models import ImageAsset, Item, MenuScan

APEX = settings.BASE_DOMAIN

CANDS = [{'url': 'https://img/a.jpg', 'page': 'https://pexels.com/p/a/',
          'credit': 'Ann', 'source': 'pexels'},
         {'url': 'https://img/b.jpg', 'page': 'https://pexels.com/p/b/',
          'credit': 'Bob', 'source': 'pexels'}]


class ItemPhotoTests(TestCase):
    def setUp(self):
        self.apex = {'HTTP_HOST': APEX}
        self.boss = User.objects.create_superuser('boss', 'b@x.io', 'pw-boss-1')
        self.scan = MenuScan.objects.create(file='scans/x.pdf', status='extracted',
                                            source_cafe='Kailash')
        self.item = Item.objects.create(
            source_scan=self.scan, status='draft', name='Chicken Momo',
            raw_name='Chicken Mo:Mo', category='Mo:Mo', reference_price=250,
            tags=['chicken', 'momo'], dietary_tags=['chicken'], source_page=2)
        self.client.force_login(self.boss)

    def _find(self, **params):
        qs = '&'.join(f'{k}={v}' for k, v in params.items())
        return self.client.get(
            f'/platform/scans/items/{self.item.pk}/find-photo/?{qs}', **self.apex)

    def _use(self, **data):
        return self.client.post(f'/platform/scans/items/{self.item.pk}/use-photo/',
                                data, **self.apex)

    def test_find_photo_requires_superuser(self):
        self.client.logout()
        self.assertEqual(self._find(offset=0).status_code, 302)

    def test_use_photo_requires_superuser(self):
        self.client.logout()
        resp = self._use(url='https://img/a.jpg', page='https://pexels.com/p/a/')
        self.assertEqual(resp.status_code, 302)
        self.item.refresh_from_db()
        self.assertIsNone(self.item.image_asset_id)

    @patch('menu.pipeline.photo_search.search', return_value=list(CANDS))
    def test_find_photo_defaults_the_term_to_the_item_name(self, m):
        body = self._find(offset=0).content.decode()
        self.assertEqual(m.call_args.args[1], 'Chicken Momo')
        self.assertIn('https://img/a.jpg', body)
        self.assertIn(f'/platform/scans/items/{self.item.pk}/find-photo/', body)
        self.assertIn(f'/platform/scans/items/{self.item.pk}/use-photo/', body)
        self.assertIn(f'#sc-card-{self.item.pk}', body)

    @patch('menu.pipeline.photo_search.search', return_value=list(CANDS))
    def test_find_photo_pages_through_candidates(self, _m):
        body = self._find(offset=1).content.decode()
        self.assertIn('https://img/b.jpg', body)

    @patch('menu.pipeline.photo_search.search', return_value=list(CANDS))
    def test_find_photo_reports_when_exhausted(self, _m):
        self.assertIn('No more results', self._find(offset=9).content.decode())

    @patch('menu.pipeline.photo_search.search', side_effect=RuntimeError('boom'))
    def test_find_photo_survives_a_dead_source(self, _m):
        self.assertIn("Couldn't reach", self._find(offset=0).content.decode())

    @patch('menu.pipeline.photo_search.search', return_value=list(CANDS))
    def test_find_photo_clear_empties_the_slot(self, _m):
        resp = self._find(clear=1)
        self.assertEqual(resp.content.decode().strip(), '')

    @patch('menu.pipeline.photo_search.search', return_value=list(CANDS))
    def test_find_photo_coerces_an_unknown_source(self, m):
        self._find(offset=0, source='hackerz')
        self.assertEqual(m.call_args.args[0], settings.SCAN_IMAGE_SOURCE)

    @patch('menu.pipeline.photo_search.fetch_thumbnail', return_value=b'WEBP')
    @patch('menu.pipeline.embed.embed', return_value=[0.3] * 768)
    def test_use_photo_creates_the_asset_and_attaches_it(self, _e, _f):
        resp = self._use(url='https://img/a.jpg', page='https://pexels.com/p/a/',
                         source='pexels')
        self.assertEqual(resp.status_code, 200)
        self.item.refresh_from_db()
        asset = ImageAsset.objects.get(origin_url='https://pexels.com/p/a/')
        self.assertEqual(self.item.image_asset_id, asset.pk)
        self.assertEqual(asset.status, 'pending')      # goes through image review
        self.assertEqual(asset.tags, ['chicken', 'momo'])   # seeded from the item
        self.assertIn('Chicken Momo', asset.caption)
        self.assertIn(f'sc-card-{self.item.pk}', resp.content.decode())

    def test_use_photo_without_a_url_is_400(self):
        resp = self._use(page='https://pexels.com/p/a/')
        self.assertEqual(resp.status_code, 400)

    @patch('menu.pipeline.photo_search.fetch_thumbnail', return_value=b'WEBP')
    @patch('menu.pipeline.intake.record', return_value=None)
    def test_use_photo_on_a_rejected_source_is_400_and_attaches_nothing(self, _r, _f):
        resp = self._use(url='https://img/a.jpg', page='https://pexels.com/p/a/')
        self.assertEqual(resp.status_code, 400)
        self.item.refresh_from_db()
        self.assertIsNone(self.item.image_asset_id)


class ItemTagEditTests(TestCase):
    def setUp(self):
        self.apex = {'HTTP_HOST': APEX}
        self.boss = User.objects.create_superuser('boss', 'b@x.io', 'pw-boss-1')
        self.scan = MenuScan.objects.create(file='scans/x.pdf', status='extracted')
        self.item = Item.objects.create(
            source_scan=self.scan, status='draft', name='Veg Mo:Mo',
            raw_name='Veg. Mo:Mo', tags=['veg'], embedding=[0.4] * 768)
        self.client.force_login(self.boss)
        self.url = f'/platform/scans/items/{self.item.pk}/tags/'

    def test_tag_edit_requires_superuser(self):
        self.client.logout()
        resp = self.client.post(self.url, {'tags': 'veg, mo:mo'}, **self.apex)
        self.assertEqual(resp.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.tags, ['veg'])

    def test_tags_are_saved_and_the_card_comes_back(self):
        resp = self.client.post(self.url, {'tags': 'veg, mo:mo'}, **self.apex)
        self.assertEqual(resp.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.tags, ['veg', 'mo:mo'])
        self.assertIn(f'sc-card-{self.item.pk}', resp.content.decode())

    def test_a_tag_absent_from_the_printed_name_is_dropped(self):
        """D6 holds on the edit path too — staff cannot type an invented tag in."""
        self.client.post(self.url, {'tags': 'veg, dumpling'}, **self.apex)
        self.item.refresh_from_db()
        self.assertEqual(self.item.tags, ['veg'])

    def test_editing_tags_does_not_re_embed(self):
        """The vector derives from name + description; tags do not touch it."""
        with patch('menu.pipeline.embed.embed',
                   side_effect=AssertionError('embedded on a tag edit')):
            resp = self.client.post(self.url, {'tags': 'veg'}, **self.apex)
        self.assertEqual(resp.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(list(self.item.embedding), [0.4] * 768)

    def test_clearing_the_box_clears_the_tags(self):
        self.client.post(self.url, {'tags': ''}, **self.apex)
        self.item.refresh_from_db()
        self.assertEqual(self.item.tags, [])
