from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from menu.models import MenuScan

APEX = settings.BASE_DOMAIN


class ScanUploadTests(TestCase):
    def setUp(self):
        self.apex = {'HTTP_HOST': APEX}
        self.boss = User.objects.create_superuser('boss', 'b@x.io', 'pw-boss-1')
        self.pleb = User.objects.create_user('pleb', 'p@x.io', 'pw-pleb-1')

    def test_scans_page_requires_superuser(self):
        self.assertEqual(self.client.get('/platform/scans/', **self.apex).status_code, 302)
        self.client.force_login(self.pleb)
        self.assertEqual(self.client.get('/platform/scans/', **self.apex).status_code, 302)

    def test_upload_creates_scan_and_enqueues(self):
        self.client.force_login(self.boss)
        f = SimpleUploadedFile("menu.pdf", b"PDFDATA", content_type="application/pdf")
        with patch('menu.tasks.extract_menu_scan.delay') as m:
            resp = self.client.post('/platform/scans/',
                                    {'source_cafe': 'Thamel Cafe', 'file': f}, **self.apex)
        self.assertIn(resp.status_code, (200, 302))
        scan = MenuScan.objects.get()
        self.assertEqual(scan.source_cafe, 'Thamel Cafe')
        self.assertEqual(scan.status, 'queued')
        self.assertTrue(scan.file.startswith('scans/'))
        m.assert_called_once_with(scan.id)

    def test_upload_requires_superuser(self):
        f = SimpleUploadedFile("menu.pdf", b"PDFDATA", content_type="application/pdf")
        resp = self.client.post('/platform/scans/', {'source_cafe': 'X', 'file': f}, **self.apex)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(MenuScan.objects.count(), 0)
