from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.home, name='home'),
    path('overview/', views.overview, name='overview'),
    path('orders/', views.orders, name='orders'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    path('items/', views.items_list, name='items_list'),
    path('items/add/', views.item_edit, name='item_add'),
    path('items/<int:pk>/', views.item_edit, name='item_edit'),
    path('items/<int:pk>/delete/', views.item_delete, name='item_delete'),
    path('items/<int:pk>/image/', views.item_image_upload, name='item_image'),

    path('categories/', views.categories_index, name='categories'),
    path('categories/add/', views.category_save, name='category_add'),
    path('categories/<int:pk>/', views.category_save, name='category_edit'),
    path('categories/<int:pk>/delete/', views.category_delete, name='category_delete'),
    path('subcategories/add/', views.subcategory_save, name='subcategory_add'),
    path('subcategories/<int:pk>/', views.subcategory_save, name='subcategory_edit'),
    path('subcategories/<int:pk>/delete/', views.subcategory_delete, name='subcategory_delete'),

    path('qr/', views.qr_index, name='qr'),
    path('qr/<int:branch_id>/generate/', views.qr_generate, name='qr_generate'),
    path('qr/<int:branch_id>/download/', views.qr_download, name='qr_download'),

    path('settings/', views.settings_index, name='settings'),
    path('settings/restaurant/', views.settings_restaurant, name='settings_restaurant'),
    path('settings/branches/add/', views.branch_save, name='branch_add'),
    path('settings/branches/<int:pk>/', views.branch_save, name='branch_edit'),
    path('settings/branches/<int:pk>/delete/', views.branch_delete, name='branch_delete'),
    path('settings/members/add/', views.member_save, name='member_add'),
    path('settings/members/<int:pk>/', views.member_save, name='member_edit'),
    path('settings/members/<int:pk>/delete/', views.member_delete, name='member_delete'),

    path('branch/<slug:slug>/', views.branch_items, name='branch_items'),
    path('branch/<slug:slug>/composition/', views.branch_composition, name='branch_composition'),
    path('branch/<slug:slug>/item/<int:pk>/price/', views.branch_item_price, name='branch_item_price'),
    path('branch/<slug:slug>/category/', views.branch_category_add, name='branch_category_add'),
    path('branch/<slug:slug>/category/<int:pk>/remove/', views.branch_category_remove, name='branch_category_remove'),
    path('branch/<slug:slug>/subcategory/', views.branch_subcategory_add, name='branch_subcategory_add'),
    path('branch/<slug:slug>/subcategory/<int:pk>/remove/', views.branch_subcategory_remove, name='branch_subcategory_remove'),
    path('branch/<slug:slug>/placements/', views.branch_placements_add, name='branch_placements_add'),
    path('branch/<slug:slug>/placement/<int:pk>/remove/', views.branch_placement_remove, name='branch_placement_remove'),
    path('branch/<slug:slug>/reorder/', views.branch_reorder, name='branch_reorder'),
    path('branch/<slug:slug>/clone/', views.branch_clone, name='branch_clone'),

    path('api/subcategories/', views.api_subcategories, name='api_subcategories'),
]
