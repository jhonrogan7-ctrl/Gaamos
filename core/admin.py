from django.contrib import admin

from .models import Lead


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("venue_name", "name", "phone", "venue_type", "created_at")
    list_filter = ("venue_type", "created_at")
    search_fields = ("venue_name", "name", "phone", "email")
    readonly_fields = ("created_at",)
