import json
from pathlib import Path

from django.conf import settings
from django.test import TestCase


class ShowcaseFixtureArtifactTest(TestCase):
    """The committed fixture + thumbnails must exist and be internally consistent.
    Guards the generated artifacts that seed_showcase depends on."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base = Path(settings.BASE_DIR)
        cls.fixture = json.loads(
            (base / 'menu' / 'fixtures' / 'showcase.json').read_text())
        cls.thumbs = base / 'static' / 'seed' / 'showcase' / 'thumbs'

    def test_counts(self):
        self.assertEqual(len(self.fixture['categories']), 8)
        subs = sum(len(c['subcategories']) for c in self.fixture['categories'])
        self.assertEqual(subs, 34)
        self.assertEqual(len(self.fixture['items']), 238)

    def test_every_item_has_a_present_static_image(self):
        for it in self.fixture['items']:
            self.assertTrue(it['image'].startswith('/static/seed/showcase/thumbs/'))
            fname = it['image'].rsplit('/', 1)[1]
            self.assertTrue((self.thumbs / fname).is_file(),
                            f"missing thumbnail for {it['slug']}: {fname}")

    def test_no_empty_subcategories_and_valid_placement(self):
        cat_slugs = {c['slug'] for c in self.fixture['categories']}
        sub_names = {(c['slug'], s['name'])
                     for c in self.fixture['categories'] for s in c['subcategories']}
        used_subs = set()
        for it in self.fixture['items']:
            self.assertIn(it['cat'], cat_slugs)
            if it['sub'] is not None:
                self.assertIn((it['cat'], it['sub']), sub_names)
                used_subs.add((it['cat'], it['sub']))
        # every declared subcategory is actually used by >=1 item
        self.assertEqual(used_subs, sub_names)
