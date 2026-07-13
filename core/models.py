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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.venue_name} — {self.name}"
