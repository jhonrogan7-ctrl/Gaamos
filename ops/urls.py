from django.urls import path

from . import views

app_name = 'ops'

urlpatterns = [
    path('', views.index, name='index'),
    path('login', views.login_view, name='login'),
    path('logout', views.logout_view, name='logout'),
    path('leads', views.leads, name='leads'),
    path('leads/<int:lead_id>/status', views.lead_status, name='lead_status'),
    path('tenants', views.tenants, name='tenants'),
    path('tenants/<int:company_id>/toggle', views.tenant_toggle, name='tenant_toggle'),
    path('tenants/<int:company_id>/reset-password', views.tenant_reset_password, name='tenant_reset_password'),
    path('tenants/<int:company_id>/impersonate', views.tenant_impersonate, name='tenant_impersonate'),
    path('tenants/new', views.tenant_new, name='tenant_new'),
    path('tenants/<int:company_id>/created', views.tenant_created, name='tenant_created'),
    path('scans/', views.scans, name='scans'),
    path('scans/<int:scan_id>/status/', views.scan_status, name='scan_status'),
    path('scans/<int:scan_id>/review/', views.scan_review, name='scan_review'),
    path('scans/items/<int:item_id>/action/', views.item_action, name='item_action'),
    path('scans/<int:scan_id>/combine/', views.scan_combine, name='scan_combine'),
    path('scans/items/<int:item_id>/find-photo/', views.item_find_photo, name='item_find_photo'),
    path('scans/items/<int:item_id>/use-photo/', views.item_use_photo, name='item_use_photo'),
    path('scans/items/<int:item_id>/tags/', views.item_edit_tags, name='item_edit_tags'),
    path('scans/<int:scan_id>/workbench/', views.scan_workbench, name='scan_workbench'),
    path('scans/<int:scan_id>/find-images/', views.scan_find_images, name='scan_find_images'),
    path('scans/<int:scan_id>/image-progress/', views.scan_image_progress, name='scan_image_progress'),
    path('scans/<int:scan_id>/publish/', views.scan_publish, name='scan_publish'),
    path('images/', views.image_review, name='images'),
    path('images/<int:asset_id>/action/', views.image_action, name='image_action'),
    path('images/<int:asset_id>/edit/', views.image_edit, name='image_edit'),
    path('images/<int:asset_id>/use-photo/', views.image_use_photo, name='image_use_photo'),
    path('images/<int:asset_id>/find-another/', views.image_find_another, name='image_find_another'),
    path('images/browse/', views.image_browse, name='image_browse'),
]
