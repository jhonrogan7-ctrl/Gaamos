from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase

from menu.models import ImageAsset

APEX = settings.BASE_DOMAIN


class ImageBrowseTests(TestCase):
    def setUp(self):
        self.apex = {'HTTP_HOST': APEX}
        self.boss = User.objects.create_superuser('boss', 'b@x.io', 'pw-boss-1')
        ImageAsset.objects.create(source='pexels', status='verified',
                                  caption='boiled egg', tags=['egg', 'breakfast'],
                                  file='imagelib/egg.webp')
        ImageAsset.objects.create(source='pexels', status='verified',
                                  caption='chicken momo', tags=['momo', 'nepali'],
                                  file='imagelib/momo.webp')
        ImageAsset.objects.create(source='pexels', status='pending',
                                  caption='pending egg', tags=['egg'],
                                  file='imagelib/p.webp')
        self.client.force_login(self.boss)

    def test_browse_requires_superuser(self):
        self.client.logout()
        resp = self.client.get('/platform/images/browse/', **self.apex)
        self.assertEqual(resp.status_code, 302)

    def test_browse_shows_only_verified(self):
        resp = self.client.get('/platform/images/browse/', **self.apex)
        self.assertContains(resp, 'boiled egg')
        self.assertContains(resp, 'chicken momo')
        self.assertNotContains(resp, 'pending egg')

    def test_text_filter(self):
        resp = self.client.get('/platform/images/browse/?q=momo', **self.apex)
        self.assertContains(resp, 'chicken momo')
        self.assertNotContains(resp, 'boiled egg')

    def test_tag_filter(self):
        resp = self.client.get('/platform/images/browse/?tag=breakfast', **self.apex)
        self.assertContains(resp, 'boiled egg')
        self.assertNotContains(resp, 'chicken momo')
