from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from core import views as core_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", core_views.healthz, name="healthz"),
    path("sw.js", core_views.service_worker, name="service_worker"),
    path("offline/", core_views.offline, name="offline"),
    path("dashboard/", include("menu.dashboard.urls")),
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

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
