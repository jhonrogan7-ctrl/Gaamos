from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from menu.models import ImageAsset

APEX = settings.BASE_DOMAIN


class ImageReviewTests(TestCase):
    def setUp(self):
        self.apex = {'HTTP_HOST': APEX}
        self.boss = User.objects.create_superuser('boss', 'b@x.io', 'pw-boss-1')
        self.pleb = User.objects.create_user('pleb', 'p@x.io', 'pw-pleb-1')
        self.asset = ImageAsset.objects.create(
            source='pexels', status='pending', caption='egg',
            file='imagelib/egg.webp', origin_url='https://x/egg.jpg')

    def test_review_queue_requires_superuser(self):
        resp = self.client.get('/platform/images/', **self.apex)
        self.assertEqual(resp.status_code, 302)
        self.client.force_login(self.pleb)
        resp = self.client.get('/platform/images/', **self.apex)
        self.assertEqual(resp.status_code, 302)

    def test_review_queue_lists_pending_for_superuser(self):
        self.client.force_login(self.boss)
        resp = self.client.get('/platform/images/', **self.apex)
        self.assertContains(resp, 'egg')

    def test_approve_marks_verified_with_reviewer(self):
        self.client.force_login(self.boss)
        resp = self.client.post(f'/platform/images/{self.asset.pk}/action/',
                                {'action': 'approve'}, **self.apex)
        self.assertEqual(resp.status_code, 302)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, 'verified')
        self.assertEqual(self.asset.reviewed_by, self.boss)
        self.assertIsNotNone(self.asset.reviewed_at)

    def test_reject_tombstones(self):
        self.client.force_login(self.boss)
        self.client.post(f'/platform/images/{self.asset.pk}/action/',
                         {'action': 'reject'}, **self.apex)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, 'rejected')

    def test_bad_action_rejected(self):
        self.client.force_login(self.boss)
        resp = self.client.post(f'/platform/images/{self.asset.pk}/action/',
                                {'action': 'nope'}, **self.apex)
        self.assertEqual(resp.status_code, 400)
