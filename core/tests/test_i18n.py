from django.conf import settings


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
