from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase

from menu.models import ImageAsset

APEX = settings.BASE_DOMAIN


def _fake_download(url, dest_path):
    from pathlib import Path
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    Path(dest_path).write_bytes(b"RAWJPEG")
    return dest_path


def _fake_thumb(src, dest, size=800):
    from pathlib import Path
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    Path(dest).write_bytes(b"WEBPBYTES")
    return dest


class ImageUsePhotoTests(TestCase):
    def setUp(self):
        self.apex = {'HTTP_HOST': APEX}
        self.boss = User.objects.create_superuser('boss', 'b@x.io', 'pw-boss-1')
        self.pleb = User.objects.create_user('pleb', 'p@x.io', 'pw-pleb-1')
        self.asset = ImageAsset.objects.create(
            source='pexels', status='pending', caption='Black Tea',
            file='imagelib/old.webp', origin_url='https://pexels.com/photo/old/',
            content_hash='oldhash')

    def _post(self, **data):
        return self.client.post(f'/platform/images/{self.asset.pk}/use-photo/',
                                data, **self.apex)

    def test_use_photo_requires_superuser(self):
        resp = self._post(url='https://img/new.jpg', page='https://pexels.com/p/new/')
        self.assertEqual(resp.status_code, 302)   # anon → login
        self.client.force_login(self.pleb)
        resp = self._post(url='https://img/new.jpg', page='https://pexels.com/p/new/')
        self.assertEqual(resp.status_code, 302)

    def test_use_photo_is_post_only(self):
        self.client.force_login(self.boss)
        resp = self.client.get(f'/platform/images/{self.asset.pk}/use-photo/', **self.apex)
        self.assertEqual(resp.status_code, 405)

    def test_missing_url_is_bad_request(self):
        self.client.force_login(self.boss)
        resp = self._post(page='https://pexels.com/p/new/')
        self.assertEqual(resp.status_code, 400)

    @patch('menu.pipeline.images.to_thumbnail', side_effect=_fake_thumb)
    @patch('menu.pipeline.find_pexels.download', side_effect=_fake_download)
    def test_use_photo_swaps_image_keeps_caption(self, m_dl, m_th):
        import hashlib
        self.client.force_login(self.boss)
        resp = self._post(url='https://img/new.jpg',
                          page='https://pexels.com/photo/new/', photographer='Ada')
        self.assertEqual(resp.status_code, 200)
        self.asset.refresh_from_db()
        h = hashlib.sha256(b"WEBPBYTES").hexdigest()
        self.assertEqual(self.asset.file, f'imagelib/{h}.webp')
        self.assertEqual(self.asset.origin_url, 'https://pexels.com/photo/new/')
        self.assertEqual(self.asset.source, 'pexels')
        self.assertEqual(self.asset.caption, 'Black Tea')      # unchanged
        self.assertEqual(self.asset.content_hash, h)

    @patch('menu.pipeline.images.to_thumbnail', side_effect=_fake_thumb)
    @patch('menu.pipeline.find_pexels.download', side_effect=_fake_download)
    def test_hash_collision_blanks_content_hash(self, m_dl, m_th):
        import hashlib
        h = hashlib.sha256(b"WEBPBYTES").hexdigest()
        ImageAsset.objects.create(source='pexels', status='verified',
                                  file='imagelib/other.webp', content_hash=h)
        self.client.force_login(self.boss)
        resp = self._post(url='https://img/new.jpg', page='https://pexels.com/photo/new/')
        self.assertEqual(resp.status_code, 200)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.file, f'imagelib/{h}.webp')
        self.assertEqual(self.asset.content_hash, '')          # collision → blank

    @patch('menu.pipeline.images.to_thumbnail', side_effect=_fake_thumb)
    @patch('menu.pipeline.find_pexels.download', side_effect=_fake_download)
    def test_origin_url_collision_blanks_origin_url(self, m_dl, m_th):
        # Other asset shares the posted page URL but NOT the content_hash, so
        # only the origin_url partial-unique constraint is exercised.
        ImageAsset.objects.create(source='pexels', status='verified',
                                  file='imagelib/other.webp',
                                  origin_url='https://pexels.com/photo/new/',
                                  content_hash='differenthash')
        self.client.force_login(self.boss)
        resp = self._post(url='https://img/new.jpg', page='https://pexels.com/photo/new/')
        self.assertEqual(resp.status_code, 200)
        self.asset.refresh_from_db()
        import hashlib
        h = hashlib.sha256(b"WEBPBYTES").hexdigest()
        self.assertEqual(self.asset.file, f'imagelib/{h}.webp')
        self.assertEqual(self.asset.origin_url, '')             # collision → blank


CANDS = [
    {'url': 'https://img/a.jpg', 'page': 'https://pexels.com/photo/a/',
     'photographer': 'Ann', 'alt': 'tea a'},
    {'url': 'https://img/b.jpg', 'page': 'https://pexels.com/photo/b/',
     'photographer': 'Bob', 'alt': 'tea b'},
    {'url': 'https://img/cur.jpg', 'page': 'https://pexels.com/photo/cur/',
     'photographer': 'Cy', 'alt': 'current'},
]


class ImageFindAnotherTests(TestCase):
    def setUp(self):
        self.apex = {'HTTP_HOST': APEX}
        self.boss = User.objects.create_superuser('boss', 'b@x.io', 'pw-boss-1')
        self.asset = ImageAsset.objects.create(
            source='pexels', status='pending', caption='Black Tea',
            file='imagelib/old.webp',
            origin_url='https://pexels.com/photo/cur/')  # matches CANDS[2] → filtered out

    def _get(self, **q):
        from urllib.parse import urlencode
        qs = ('?' + urlencode(q)) if q else ''
        return self.client.get(f'/platform/images/{self.asset.pk}/find-another/{qs}',
                               **self.apex)

    def test_requires_superuser(self):
        self.assertEqual(self._get(offset=0).status_code, 302)

    @patch('menu.pipeline.find_pexels.search', return_value=list(CANDS))
    def test_offset_zero_shows_first_non_current_candidate(self, m):
        self.client.force_login(self.boss)
        resp = self._get(offset=0)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('https://img/a.jpg', body)         # candidate[0] after filtering current
        self.assertNotIn('https://img/cur.jpg', body)    # current photo excluded
        self.assertIn('offset=1', body)                  # Find another advances

    @patch('menu.pipeline.find_pexels.search', return_value=list(CANDS))
    def test_offset_one_shows_second(self, m):
        self.client.force_login(self.boss)
        body = self._get(offset=1).content.decode()
        self.assertIn('https://img/b.jpg', body)

    @patch('menu.pipeline.find_pexels.search', return_value=list(CANDS))
    def test_offset_past_end_shows_no_more(self, m):
        self.client.force_login(self.boss)
        body = self._get(offset=9).content.decode()
        self.assertIn('No more new photos', body)

    def test_clear_returns_empty(self):
        self.client.force_login(self.boss)
        resp = self._get(clear=1)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content.decode().strip(), '')

    @patch('menu.pipeline.find_pexels.search', side_effect=RuntimeError('boom'))
    def test_pexels_error_shows_friendly_message(self, m):
        self.client.force_login(self.boss)
        resp = self._get(offset=0)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Couldn't reach Pexels", resp.content.decode())
