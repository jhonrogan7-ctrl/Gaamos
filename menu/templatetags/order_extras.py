"""Order-card presentation filters (Orders page card redesign, 2026-08-27)."""
from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def smart_datetime(dt):
    """Variant-A order timestamp: "Today · 14:32" / "Yesterday · 21:07" /
    "26 Aug · 09:15". Venue-local. Blank for None."""
    if dt is None:
        return ""
    local = timezone.localtime(dt)
    today = timezone.localdate()
    delta_days = (today - local.date()).days
    if delta_days == 0:
        day = "Today"
    elif delta_days == 1:
        day = "Yesterday"
    else:
        day = f"{local.day} {local:%b}"
    return f"{day} · {local:%H:%M}"
