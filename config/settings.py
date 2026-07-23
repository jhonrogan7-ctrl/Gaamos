import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "django-insecure-dev-only")
DEBUG = os.environ.get("DEBUG", "0") == "1"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")
BASE_DOMAIN = os.environ.get("BASE_DOMAIN", "zxyn.online")
RESERVED_SUBDOMAINS = {"app", "www", "menu", "admin", "api", "static", "media", "gaamos"}

# Behind Cloudflare Tunnel — TLS terminated at the edge, forwarded as plain HTTP.
# Trust the forwarded proto so Django treats requests as secure and CSRF accepts
# the HTTPS origin (login/POST would otherwise 403). Locked stack decision.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = os.environ.get(
    "CSRF_TRUSTED_ORIGINS", f"https://{BASE_DOMAIN},https://*.{BASE_DOMAIN}"
).split(",")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.admin",
    "django.contrib.messages",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "core",
    "menu",
    "ops",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "menu.middleware.TenantMiddleware",
    "menu.middleware.MembershipMiddleware",
    "menu.middleware.RateLimitMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "core.context_processors.asset_version",
        "core.context_processors.base_domain",
    ]},
}]

WSGI_APPLICATION = "config.wsgi.application"

LOGIN_URL = "/dashboard/login/"

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
GUEST_RATE_LIMIT = int(os.environ.get("GUEST_RATE_LIMIT", "120"))
GUEST_RATE_WINDOW = int(os.environ.get("GUEST_RATE_WINDOW", "60"))

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "gaamos"),
        "USER": os.environ.get("POSTGRES_USER", "gaamos"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "gaamos"),
        "HOST": os.environ.get("POSTGRES_HOST", "db"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("ne", "नेपाली"), ("ka", "ქართული")]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Asia/Kathmandu"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

MEDIA_URL = "/media/"
MEDIA_ROOT = os.environ.get("MEDIA_ROOT", str(BASE_DIR / "media"))

# Google Gemini / Imagen — image generation for the menu-from-pdf pipeline.
# Key lives only in .env (gitignored); never commit it.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
GEMINI_EMBED_MODEL = os.environ.get("GEMINI_EMBED_MODEL", "text-embedding-004")
GEMINI_VISION_MODEL = os.environ.get("GEMINI_VISION_MODEL", "gemini-2.5-flash")
LIBRARY_MATCH_THRESHOLD = float(os.environ.get("LIBRARY_MATCH_THRESHOLD", "0.75"))
ITEM_MATCH_THRESHOLD = float(os.environ.get("ITEM_MATCH_THRESHOLD", "0.85"))
# Below this extractor confidence a scanned item is flagged for human review.
SCAN_CONFIDENCE_THRESHOLD = float(os.environ.get("SCAN_CONFIDENCE_THRESHOLD", "0.7"))

# Free stock-photo APIs for the image 'find' path (all from .env, never committed).
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
OPENVERSE_CLIENT_ID = os.environ.get("OPENVERSE_CLIENT_ID", "")
OPENVERSE_CLIENT_SECRET = os.environ.get("OPENVERSE_CLIENT_SECRET", "")

# Celery + Redis — background-job foundation.
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "0") == "1"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
