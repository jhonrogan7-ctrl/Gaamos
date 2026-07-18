from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from .models import Lead


def healthz(request):
    return JsonResponse({"status": "ok"})


def service_worker(request):
    sw_path = settings.BASE_DIR / "static" / "pwa" / "sw.js"
    content = sw_path.read_text()
    response = HttpResponse(content, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    return response


def offline(request):
    """Precached by the service worker; served on failed navigations."""
    return render(request, "offline.html")


VENUE_TYPES = [c[0] for c in Lead.VENUE_TYPES]

LIVE_ORDERS = [
    {"id": "#3", "table": _("Table 6"), "items": "Plain Toast ×1, Cheese Toast ×1, Cheese Tomato Toast ×1", "status": "New", "status_label": _("New")},
    {"id": "#2", "table": _("Takeaway"), "items": "American Breakfast ×1, Special Breakfast ×1", "status": "New", "status_label": _("New")},
    {"id": "#1", "table": _("Table 2"), "items": "French Toast ×1, Plain Toast ×2", "status": "Served", "status_label": _("Served")},
]
BUILDER_ITEMS = [
    {"name": "Black Tea", "price": "Rs 40"},
    {"name": "Masala Tea", "price": "Rs 70"},
    {"name": "Milk Coffee", "price": "Rs 90"},
    {"name": "Hot Chocolate", "price": "Rs 210"},
]
STEPS = [
    {"n": "1", "title": _("Build your menu"), "body": _("Pick dishes from the template library, set prices, add photos. Organize into categories your guests will actually browse.")},
    {"n": "2", "title": _("Print your QRs"), "body": _("Generate one code for the counter or a numbered code per table. Download the whole set as a print-ready PDF.")},
    {"n": "3", "title": _("Receive orders"), "body": _("Guests scan, browse, and order from their own phone. Orders appear in your live queue the moment they're placed.")},
]
BRANCHES = [
    {"initials": "MG", "name": "Momo Ghar — Lakeside", "prefix": "momoghar", "orders": "42"},
    {"initials": "MG", "name": "Momo Ghar — City Center", "prefix": "momoghar-city", "orders": "31"},
    {"initials": "TC", "name": "The Terrace Café", "prefix": "theterrace", "orders": "18"},
]
TIERS = [
    {"name": _("Business"), "price": "Rs 3,000", "per": _("/month"),
     "blurb": _("The whole product — everything your venue needs to run QR menus and live orders."),
     "cta": _("Get started"), "highlighted": True, "features": [
        _("Unlimited branches & menu items"),
        _("Branded QR menu — 3 themes × 3 layouts"),
        _("Guest ordering + live order queue"),
        _("Table QRs + printable PDF export"),
        _("Photos, badges & promo banner"),
        _("Installable app (PWA) for guests & staff"),
        _("3 team members"),
    ]},
    {"name": _("VIP"), "price": "Rs 7,000", "per": _("/month"),
     "blurb": _("For venues that want full brand ownership and a bigger team."),
     "cta": _("Talk to us"), "highlighted": False, "features": [
        _("Everything in Business"),
        _("Custom domain — menu.yourrestaurant.com"),
        _("Your venue as its own branded app"),
        _("Unlimited team + branch-scoped managers"),
        _("Priority WhatsApp support"),
    ]},
]
TABLE_QRS = ["1", "2", "3", "4", "5", "6", "7", "8"]


def _landing_context(**extra):
    ctx = {
        "live_orders": LIVE_ORDERS,
        "builder_items": BUILDER_ITEMS,
        "steps": STEPS,
        "branches": BRANCHES,
        "tiers": TIERS,
        "table_qrs": TABLE_QRS,
        "venue_types": Lead.VENUE_TYPES,
    }
    ctx.update(extra)
    return ctx


def _apex_only(request):
    """Marketing views never render on tenant subdomains — <slug>.<base>/ne/ must 404."""
    if getattr(request, "company", None) is not None:
        raise Http404


def home(request):
    _apex_only(request)
    return render(request, "home.html", _landing_context())


def contact(request):
    """Landing lead-capture. HTMX requests get form/success fragments;
    non-HTMX requests get the full landing page (progressive enhancement)."""
    _apex_only(request)
    is_htmx = request.headers.get("HX-Request") == "true"
    if request.method == "POST":
        values = {
            "name": request.POST.get("name", "").strip(),
            "venue_name": request.POST.get("venue_name", "").strip(),
            "phone": request.POST.get("phone", "").strip(),
            "email": request.POST.get("email", "").strip(),
            "venue_type": request.POST.get("venue_type", "Café").strip() or "Café",
            "message": request.POST.get("message", "").strip(),
        }
        if values["venue_type"] not in VENUE_TYPES:
            values["venue_type"] = "Café"
        if not (values["name"] and values["venue_name"] and values["phone"]):
            error = _("Please fill in your name, venue name and phone number.")
            if is_htmx:
                return render(request, "marketing/_contact_form.html", {
                    "error": error, "values": values, "venue_types": Lead.VENUE_TYPES,
                })
            return render(request, "home.html", _landing_context(
                contact_error=error, contact_values=values,
            ))
        Lead.objects.create(**values)
        if is_htmx:
            return render(request, "marketing/_contact_success.html")
        return render(request, "home.html", _landing_context(contact_sent=True))
    # GET
    if is_htmx:
        return render(request, "marketing/_contact_form.html", {"venue_types": Lead.VENUE_TYPES})
    return redirect(reverse("home") + "#contact")
