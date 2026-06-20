from django.urls import path
from . import views

urlpatterns = [
    path('', views.root, name='menu'),
    path('api/order/', views.place_order, name='place_order'),
]
