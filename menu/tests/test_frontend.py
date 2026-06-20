from pathlib import Path
from django.conf import settings
from django.test import SimpleTestCase


class CssBuildTest(SimpleTestCase):
    def test_app_css_built_and_nonempty(self):
        css = Path(settings.BASE_DIR) / 'static' / 'css' / 'app.css'
        self.assertTrue(css.exists(), 'app.css not built — run bin/build-css.sh')
        self.assertGreater(css.stat().st_size, 1000, 'app.css suspiciously small')


class CssComponentsTest(SimpleTestCase):
    def _css(self):
        from pathlib import Path
        from django.conf import settings
        return (Path(settings.BASE_DIR) / 'static/css/app.css').read_text()

    def test_core_component_classes_present(self):
        css = self._css()
        for sel in ['.btn', '.panel', '.side', '.nav', '.tbl', '.stat', '.focal']:
            self.assertIn(sel, css, f'missing component class {sel}')
