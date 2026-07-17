import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

APEX = settings.BASE_DOMAIN


class OpsManifestTest(SimpleTestCase):
    def test_ops_manifest_scoped_to_platform(self):
        pwa = Path(settings.BASE_DIR) / 'static' / 'pwa'
        ops = json.loads((pwa / 'manifest-ops.webmanifest').read_text())
        self.assertEqual(ops['id'], '/platform/')
        self.assertEqual(ops['start_url'], '/platform/')
        self.assertEqual(ops['scope'], '/platform/')
        self.assertEqual(ops['name'], 'Gaamos Ops')
        self.assertEqual(ops['display'], 'standalone')
        self.assertEqual({i['sizes'] for i in ops['icons']}, {'192x192', '512x512'})


class OpsPwaWiringTest(TestCase):
    def setUp(self):
        self.apex = {'HTTP_HOST': APEX}
        boss = User.objects.create_superuser('boss', 'b@x.io', 'pw')
        self.client.force_login(boss)

    def test_ops_base_links_manifest_and_registers_sw(self):
        body = self.client.get('/platform/leads', **self.apex).content.decode()
        self.assertIn('manifest-ops.webmanifest', body)
        self.assertIn('serviceWorker', body)
        self.assertIn('apple-touch-icon', body)
        self.assertIn('apple-mobile-web-app-capable', body)
