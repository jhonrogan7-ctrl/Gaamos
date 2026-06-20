from pathlib import Path
from django.conf import settings
from django.test import SimpleTestCase


class CssBuildTest(SimpleTestCase):
    def test_app_css_built_and_nonempty(self):
        css = Path(settings.BASE_DIR) / 'static' / 'css' / 'app.css'
        self.assertTrue(css.exists(), 'app.css not built — run bin/build-css.sh')
        self.assertGreater(css.stat().st_size, 1000, 'app.css suspiciously small')
