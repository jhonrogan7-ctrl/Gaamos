"""Branch Theme tab: picker partial, tab rendering, save endpoint, access."""
from django.template import Context, Template
from django.test import SimpleTestCase


def render_picker(**kwargs):
    ctx = Context(kwargs)
    args = ' '.join(f'{k}={k}' for k in kwargs)
    return Template('{% load theme_tags %}{% theme_picker ' + args + ' %}').render(ctx)


class ThemePickerInheritCardTest(SimpleTestCase):
    def test_submit_mode_inherit_card_is_submit_button(self):
        html = render_picker(current='', include_inherit=True)
        self.assertIn('name="menu_theme" value=""', html)
        self.assertIn('Company default', html)
        self.assertNotIn('bTheme', html)  # no Alpine leakage in submit mode
        # inherit + 6 themes, all submit buttons
        self.assertEqual(html.count('name="menu_theme"'), 7)

    def test_inherit_card_on_only_when_inheriting(self):
        html = render_picker(current='', include_inherit=True)
        self.assertEqual(html.count('class="theme on"'), 1)
        self.assertLess(html.index('class="theme on"'), html.index('Classic Fast Food'))
        html = render_picker(current='eco', include_inherit=True)
        self.assertEqual(html.count('class="theme on"'), 1)
        self.assertGreater(html.index('class="theme on"'), html.index('Company default'))

    def test_alpine_mode_unchanged(self):
        html = render_picker(current='', include_inherit=True, alpine=True)
        self.assertIn('@click="bTheme=\'\'"', html)
        self.assertEqual(html.count('@click="bTheme='), 7)
        self.assertNotIn('type="submit"', html)

    def test_settings_mode_without_inherit_unchanged(self):
        html = render_picker(current='eco')
        self.assertNotIn('Company default', html)
        self.assertEqual(html.count('name="menu_theme"'), 6)
