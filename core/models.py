from django.db import models
from django.utils.translation import gettext_lazy as _


class Lead(models.Model):
    """A marketing "request a callback" submission from the landing page.

    Stored venue_type values stay canonical English; only labels are localized."""

    VENUE_TYPES = [
        ("Café", _("Café")),
        ("Restaurant", _("Restaurant")),
        ("Bar", _("Bar")),
        ("Other", _("Other")),
    ]

    name = models.CharField(max_length=120)
    venue_name = models.CharField(max_length=160)
    phone = models.CharField(max_length=40)
    email = models.EmailField(blank=True)
    venue_type = models.CharField(max_length=20, choices=VENUE_TYPES, default="Café")
    message = models.TextField(blank=True)
    STATUS_CHOICES = [
        ("new", "New"), ("contacted", "Contacted"),
        ("converted", "Converted"), ("rejected", "Rejected"),
    ]
    status = models.CharField(max_length=20, default="new",
                              choices=STATUS_CHOICES, db_index=True)
    company = models.ForeignKey("menu.Company", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="leads")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.venue_name} — {self.name}"
