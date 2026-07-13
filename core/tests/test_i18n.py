import pytest
from django.conf import settings

from menu.models import Company


def test_languages_configured():
    assert [code for code, _ in settings.LANGUAGES] == ["en", "ne", "ka"]
    assert settings.LANGUAGE_CODE == "en"
    assert settings.USE_I18N is True
    assert str(settings.LOCALE_PATHS[0]).endswith("locale")


def test_locale_middleware_between_session_and_common():
    mw = settings.MIDDLEWARE
    assert (
        mw.index("django.contrib.sessions.middleware.SessionMiddleware")
        < mw.index("django.middleware.locale.LocaleMiddleware")
        < mw.index("django.middleware.common.CommonMiddleware")
    )


@pytest.mark.django_db
def test_prefixed_landing_renders_for_all_languages(client):
    for lang in ("en", "ne", "ka"):
        resp = client.get(f"/{lang}/")
        assert resp.status_code == 200, lang
        assert "Gaamos" in resp.content.decode()


@pytest.mark.django_db
def test_unsupported_language_prefix_404(client):
    assert client.get("/fr/").status_code == 404


@pytest.mark.django_db
def test_apex_redirects_by_accept_language(client):
    assert client.get("/", HTTP_ACCEPT_LANGUAGE="ne")["Location"] == "/ne/"
    assert client.get("/", HTTP_ACCEPT_LANGUAGE="ka,en;q=0.5")["Location"] == "/ka/"
    assert client.get("/", HTTP_ACCEPT_LANGUAGE="fr")["Location"] == "/en/"
    assert client.get("/")["Location"] == "/en/"


@pytest.mark.django_db
def test_tenant_host_untouched(client, settings):
    Company.objects.create(name="Test Co", slug="testco")
    host = f"testco.{settings.BASE_DOMAIN}"
    assert client.get("/", HTTP_HOST=host).status_code == 200          # guest menu
    assert client.get("/ne/", HTTP_HOST=host).status_code == 404       # no marketing on tenant
    assert client.get("/en/contact", HTTP_HOST=host).status_code == 404


@pytest.mark.django_db
def test_venue_type_chips_submit_canonical_values(client):
    body = client.get("/en/").content.decode()
    # chips render labels AND wire canonical values into Alpine
    assert "vtype = 'Café'" in body
    assert "vtype = 'Restaurant'" in body


def test_venue_type_stored_values_stay_canonical():
    from core.models import Lead
    assert [v for v, _ in Lead.VENUE_TYPES] == ["Café", "Restaurant", "Bar", "Other"]


@pytest.mark.django_db
def test_html_lang_matches_url_prefix(client):
    assert 'lang="ne"' in client.get("/ne/").content.decode()
    assert 'lang="en"' in client.get("/en/").content.decode()


@pytest.mark.django_db
def test_nav_language_switcher_links(client):
    body = client.get("/en/").content.decode()
    for href in ('href="/en/"', 'href="/ne/"', 'href="/ka/"'):
        assert href in body
    assert "ने" in body and "ქა" in body


@pytest.mark.django_db
def test_hreflang_alternates_in_head(client, settings):
    body = client.get("/en/").content.decode()
    for lang in ("en", "ne", "ka"):
        assert f'hreflang="{lang}" href="https://{settings.BASE_DOMAIN}/{lang}/"' in body
    assert 'hreflang="x-default"' in body


@pytest.mark.django_db
def test_script_fonts_requested(client):
    body = client.get("/en/").content.decode()
    assert "Noto+Sans+Devanagari" in body
    assert "Noto+Sans+Georgian" in body
