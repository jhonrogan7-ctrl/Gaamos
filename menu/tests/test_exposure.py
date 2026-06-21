from django.core.cache import cache
from django.test import TestCase, RequestFactory, override_settings
from django.http import HttpResponse

from menu.middleware import RateLimitMiddleware


@override_settings(GUEST_RATE_LIMIT=5, GUEST_RATE_WINDOW=60)
class RateLimitTest(TestCase):
    def setUp(self):
        cache.clear()
        self.rf = RequestFactory()
        self.mw = RateLimitMiddleware(lambda req: HttpResponse('ok'))

    def test_single_load_passes(self):
        resp = self.mw(self.rf.get('/', REMOTE_ADDR='1.2.3.4'))
        self.assertEqual(resp.status_code, 200)

    def test_rapid_sweep_throttled(self):
        statuses = [self.mw(self.rf.get('/', REMOTE_ADDR='9.9.9.9')).status_code
                    for _ in range(8)]
        self.assertIn(429, statuses)
        self.assertEqual(statuses[0], 200)

    def test_separate_ips_independent(self):
        statuses = [self.mw(self.rf.get('/', REMOTE_ADDR='9.9.9.9')).status_code
                    for _ in range(6)]
        self.assertEqual(statuses[-1], 429)  # 9.9.9.9 is now throttled
        resp = self.mw(self.rf.get('/', REMOTE_ADDR='5.5.5.5'))
        self.assertEqual(resp.status_code, 200)  # different IP unaffected

    def test_dashboard_and_static_paths_exempt(self):
        # The throttle guards guest menu reads, not the authenticated dashboard,
        # the admin, or static assets — those must never 429 on a rapid sweep.
        for path in ('/dashboard/', '/dashboard/items/', '/static/css/app.css', '/admin/'):
            statuses = [self.mw(self.rf.get(path, REMOTE_ADDR='7.7.7.7')).status_code
                        for _ in range(8)]
            self.assertNotIn(429, statuses, path)
