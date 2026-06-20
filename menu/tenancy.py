import contextvars

from django.db import models

_current_company = contextvars.ContextVar('current_company', default=None)


def set_current_company(company):
    """Set the active company for this execution context. Returns a token for reset()."""
    return _current_company.set(company)


def get_current_company():
    return _current_company.get()


def reset_current_company(token):
    _current_company.reset(token)


class TenantContextRequired(RuntimeError):
    """Raised when a tenant-scoped query runs with no company in context."""


class TenantManager(models.Manager):
    """Default manager for tenant-scoped models. FAIL-CLOSED: with no company in
    context it RAISES rather than returning all rows."""

    def get_queryset(self):
        company = get_current_company()
        if company is None:
            raise TenantContextRequired(
                f"{self.model.__name__}.objects used with no company context. "
                f"Use {self.model.__name__}.all_objects for deliberate cross-tenant access."
            )
        return super().get_queryset().filter(company=company)


class TenantScopedModel(models.Model):
    """Abstract base for tenant-scoped models. Concrete subclasses declare their own
    `company` ForeignKey (for an explicit related_name). This base supplies the two
    managers, pins the base manager to the unfiltered one, and auto-stamps `company`
    from context on save (defense-in-depth)."""

    objects = TenantManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True
        base_manager_name = 'all_objects'

    def save(self, *args, **kwargs):
        if getattr(self, 'company_id', None) is None:
            current = get_current_company()
            if current is not None:
                self.company = current
        super().save(*args, **kwargs)
