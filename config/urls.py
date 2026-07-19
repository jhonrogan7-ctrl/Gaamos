from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

from core import views as core_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", core_views.healthz, name="healthz"),
    path("sw.js", core_views.service_worker, name="service_worker"),
    path("offline/", core_views.offline, name="offline"),
    path("dashboard/", include("menu.dashboard.urls")),
    path("platform/", include("ops.urls")),
]

# Marketing landing — language-prefixed (/en/ /ne/ /ka/). Tenant hosts 404 these
# views (guard in core.views); the apex root redirect lives in menu.views.root.
urlpatterns += i18n_patterns(
    path("", core_views.home, name="home"),
    path("contact", core_views.contact, name="contact"),
    prefix_default_language=True,
)

urlpatterns += [
    path("", include("menu.urls")),
]

# Serve tenant media (QR PNGs, logos) from Django in every environment. These
# files are generated at runtime, so WhiteNoise (static-only, manifest built at
# boot) can't serve them, and the stack has no separate media server — Cloudflare
# fronts uvicorn directly. django.conf.urls.static.static() no-ops when DEBUG is
# False, so the route is wired explicitly here. All media is public by design
# (QR codes are printed to scan; logos are branding), so no auth gate is needed.
urlpatterns += [
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]
