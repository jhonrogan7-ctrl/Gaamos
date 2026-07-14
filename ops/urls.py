from django.urls import path

from . import views

app_name = 'ops'

urlpatterns = [
    path('login', views.login_view, name='login'),
    path('logout', views.logout_view, name='logout'),
    path('leads', views.leads, name='leads'),
    # placeholders — replaced by real views in the next tasks
    path('tenants', views.leads, name='tenants'),
    path('tenants/new', views.leads, name='tenant_new'),
]
