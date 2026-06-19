from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("healthz", views.healthz, name="healthz"),
    path("sw.js", views.service_worker, name="service_worker"),
]
