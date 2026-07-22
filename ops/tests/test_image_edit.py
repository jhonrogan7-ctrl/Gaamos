from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase

from menu.models import ImageAsset

APEX = settings.BASE_DOMAIN


class ImageEditTests(TestCase):
    def setUp(self):
        self.apex = {'HTTP_HOST': APEX}
        self.boss = User.objects.create_superuser('boss', 'b@x.io', 'pw-boss-1')
        self.asset = ImageAsset.objects.create(
            source='pexels', status='pending', caption='egg',
            tags=['egg'], embedding=[0.1] * 768, file='imagelib/egg.webp')
        self.client.force_login(self.boss)

    def test_edit_tags_only_does_not_reembed(self):
        with patch('menu.pipeline.embed.embed') as m:
            self.client.post(f'/platform/images/{self.asset.pk}/edit/',
                             {'caption': 'egg', 'tags': 'egg, breakfast'}, **self.apex)
            m.assert_not_called()
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.tags, ['egg', 'breakfast'])

    def test_edit_caption_reembeds(self):
        with patch('menu.pipeline.embed.embed', return_value=[0.9] * 768) as m:
            self.client.post(f'/platform/images/{self.asset.pk}/edit/',
                             {'caption': 'halved boiled egg', 'tags': 'egg'}, **self.apex)
            m.assert_called_once_with('halved boiled egg')
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.caption, 'halved boiled egg')
        self.assertEqual(list(self.asset.embedding), [0.9] * 768)
