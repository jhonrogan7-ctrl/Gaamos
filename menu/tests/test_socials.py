"""Turning whatever a venue typed into a link the guest menu can safely open.

The stored value is free text and always has been: fixtures and `seed_venue`
carry bare handles, while an owner pasting from a browser gives a full URL.
Both have to work, and neither may produce an `href` we would not click
ourselves.
"""
import pytest

from menu.socials import social_link


@pytest.mark.parametrize("stored", ["chillzone", "@chillzone", " @chillzone "])
def test_a_handle_becomes_the_networks_own_url(stored):
    link = social_link("instagram", stored)
    assert link == {"url": "https://instagram.com/chillzone", "handle": "@chillzone"}


def test_a_pasted_url_is_kept_as_the_venue_pasted_it():
    link = social_link("instagram", "https://instagram.com/chillzone")
    assert link["url"] == "https://instagram.com/chillzone"
    assert link["handle"] == "@chillzone"


def test_a_bare_domain_gains_a_scheme():
    """`instagram.com/x` in an href without a scheme resolves against our own
    host, so the row would link the guest back into the menu."""
    assert social_link("instagram", "instagram.com/chillzone")["url"] == \
        "https://instagram.com/chillzone"
    assert social_link("facebook", "www.facebook.com/momoghar")["url"] == \
        "https://www.facebook.com/momoghar"


def test_http_is_upgraded_to_https():
    assert social_link("facebook", "http://facebook.com/momoghar")["url"] == \
        "https://facebook.com/momoghar"


def test_facebook_handles_are_shown_without_an_at_sign():
    """Pages are not @handles; Instagram and TikTok ones are."""
    assert social_link("facebook", "momoghar")["handle"] == "momoghar"
    assert social_link("tiktok", "momoghar")["handle"] == "@momoghar"


def test_a_url_that_is_not_a_single_handle_shows_its_trimmed_address():
    """A numeric profile link has no handle to show, and inventing one would
    print something the guest cannot search for."""
    link = social_link("facebook", "https://facebook.com/profile.php?id=61551")
    assert link["url"] == "https://facebook.com/profile.php?id=61551"
    assert link["handle"] == "facebook.com/profile.php"


@pytest.mark.parametrize("stored", ["", "   ", "@", "https://", "/"])
def test_nothing_worth_linking_yields_none(stored):
    """None is what hides the row. An empty row with an icon and no value looks
    like a broken page, not an unset setting."""
    for network in ("instagram", "facebook", "tiktok"):
        assert social_link(network, stored) is None


@pytest.mark.parametrize("network", ["instagram", "facebook", "tiktok"])
@pytest.mark.parametrize("stored", [
    "javascript:alert(1)",
    "JavaScript:alert(1)",
    "  javascript:alert(1)",
    "data:text/html;base64,PHNjcmlwdD4=",
    "vbscript:msgbox(1)",
    "file:///etc/passwd",
])
def test_only_http_urls_are_ever_linked(network, stored):
    """This is the whole reason the function exists. The value is tenant-typed
    text going into an href on a page every guest opens; a scheme that is not
    http(s) must never survive, whatever case it was typed in."""
    assert social_link(network, stored) is None


def test_a_word_can_never_become_a_scheme():
    """Belt and braces on the handle path: a colon in a bare value must not be
    smuggled through as a scheme by the URL builder."""
    link = social_link("instagram", "javascript:alert(1)")
    assert link is None


def test_an_unknown_network_is_refused():
    assert social_link("myspace", "chillzone") is None
