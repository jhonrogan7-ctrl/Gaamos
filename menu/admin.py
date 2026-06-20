from django.contrib import admin

from .models import (
    Company, Branch, Category, SubCategory, MenuItem,
    BranchMenuItem, BranchCategory, BranchSubCategory, BranchItemPlacement,
)


class TenantScopedAdmin(admin.ModelAdmin):
    """Admin sees across all tenants via the unfiltered base manager."""

    def get_queryset(self, request):
        return self.model.all_objects.get_queryset()


admin.site.register(Company)
for _model in (Branch, Category, SubCategory, MenuItem):
    admin.site.register(_model, TenantScopedAdmin)
for _model in (BranchMenuItem, BranchCategory, BranchSubCategory, BranchItemPlacement):
    admin.site.register(_model)
