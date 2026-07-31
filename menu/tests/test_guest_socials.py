"""The venue's socials, from the Settings field to the guest contact sheet.

`Company.instagram`/`.facebook`/`.tiktok` shipped in the first migration and
Settings has saved them ever since, but nothing read them — the sheet showed
phone and email only. These pin the wiring so they cannot go quiet again.
"""
import json
import re

from menu.tests.base import TenantTestCase


def payload(body):
    """The JSON the guest page hands Alpine, out of its json_script tag."""
    match = re.search(
        r'<script id="menu-data" type="application/json">(.*?)</script>', body, re.S)
    return json.loads(match.group(1))


class GuestSocialPayloadTest(TenantTestCase):
    def _restaurant(self):
        body = self.client.get('/').content.decode()
        return payload(body)['restaurant']

    def test_a_filled_network_arrives_as_a_url_and_a_handle(self):
        self.company.instagram = '@chillzone'
        self.company.facebook = 'https://facebook.com/momoghar'
        self.company.save()

        restaurant = self._restaurant()
        assert restaurant['instagram'] == {
            'url': 'https://instagram.com/chillzone', 'handle': '@chillzone'}
        assert restaurant['facebook']['url'] == 'https://facebook.com/momoghar'

    def test_an_empty_network_is_null_so_its_row_never_renders(self):
        restaurant = self._restaurant()
        assert restaurant['instagram'] is None
        assert restaurant['facebook'] is None
        assert restaurant['tiktok'] is None

    def test_an_unsafe_stored_value_never_reaches_the_page(self):
        """A venue (or a staff member typing into the ops form) cannot put a
        javascript: URL in front of every guest who opens the sheet."""
        self.company.instagram = 'javascript:alert(1)'
        self.company.save()

        body = self.client.get('/').content.decode()
        assert payload(body)['restaurant']['instagram'] is None
        assert 'javascript:alert' not in body


class GuestSocialMarkupTest(TenantTestCase):
    def test_each_network_has_a_row_bound_to_its_own_link(self):
        body = self.client.get('/').content.decode()
        for network, icon in (('instagram', 'insta'),
                              ('facebook', 'fb'),
                              ('tiktok', 'tiktok')):
            assert f'x-if="restaurant.{network}"' in body, network
            assert f':href="restaurant.{network}.url"' in body, network
            assert f'x-text="restaurant.{network}.handle"' in body, network
            assert f"icon('{icon}')" in body, network

    def test_the_rows_open_out_of_the_menu_safely(self):
        """target=_blank without rel=noopener hands the opened tab a handle on
        the menu it came from."""
        body = self.client.get('/').content.decode()
        section = body[body.index('Get in touch'):body.index('Our locations')]
        assert section.count('target="_blank"') == 3
        assert section.count('rel="noopener noreferrer"') == 3

    def test_the_icons_the_rows_ask_for_exist(self):
        """`icon()` renders an unknown key as nothing, so a typo here is an
        invisible failure: the row would show a blank tile and still pass."""
        from menu.tests.icons_js import defined_icon_keys

        assert {'insta', 'fb', 'tiktok'} <= defined_icon_keys()


class SettingsSocialsTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_user('owner', password='pw')
        self.make_owner(user)
        self.client.login(username='owner', password='pw')

    def test_an_owner_can_save_a_pasted_link_and_the_menu_shows_it(self):
        resp = self.client.post('/dashboard/settings/restaurant/', {
            'name': 'Test Co', 'tagline': '', 'phone': '', 'email': '',
            'instagram': 'https://www.instagram.com/chillzone',
            'facebook': 'momoghar', 'tiktok': '',
        })
        assert resp.status_code == 302

        self.company.refresh_from_db()
        assert self.company.instagram == 'https://www.instagram.com/chillzone'

        restaurant = payload(self.client.get('/').content.decode())['restaurant']
        assert restaurant['instagram']['url'] == 'https://www.instagram.com/chillzone'
        assert restaurant['facebook'] == {
            'url': 'https://facebook.com/momoghar', 'handle': 'momoghar'}
        assert restaurant['tiktok'] is None
