from django.urls import path
from . import views

urlpatterns = [
    path('', views.root, name='menu'),
    path('api/order/', views.place_order, name='place_order'),
    path('api/identity/', views.identity_submit, name='identity_submit'),
    path('api/otp/verify/', views.otp_verify, name='otp_verify'),
    path('api/otp/resend/', views.otp_resend, name='otp_resend'),
]
