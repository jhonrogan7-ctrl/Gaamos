from django.urls import path

from . import views

app_name = 'ops'

urlpatterns = [
    path('login', views.login_view, name='login'),
    path('logout', views.logout_view, name='logout'),
    path('leads', views.leads, name='leads'),
    path('leads/<int:lead_id>/status', views.lead_status, name='lead_status'),
    path('tenants', views.tenants, name='tenants'),
    path('tenants/<int:company_id>/toggle', views.tenant_toggle, name='tenant_toggle'),
    path('tenants/<int:company_id>/reset-password', views.tenant_reset_password, name='tenant_reset_password'),
    # placeholder — replaced by the create-tenant task
    path('tenants/new', views.leads, name='tenant_new'),
]
