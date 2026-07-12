from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render

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

HERO_ORDERS = [
    {"id": "#7", "table": "Table 12", "items": "Cappuccino ×2, French Toast ×1", "total": "Rs 590", "status": "New"},
    {"id": "#6", "table": "Takeaway", "items": "Cheese Toast ×1, Milk Tea ×2", "total": "Rs 300", "status": "New"},
    {"id": "#5", "table": "Table 4", "items": "American Breakfast ×1, Black Coffee ×1", "total": "Rs 430", "status": "Served"},
    {"id": "#4", "table": "Table 9", "items": "Hot Chocolate ×2, Plain Toast ×1", "total": "Rs 520", "status": "Served"},
]
LIVE_ORDERS = [
    {"id": "#3", "table": "Table 6", "items": "Plain Toast ×1, Cheese Toast ×1, Cheese Tomato Toast ×1", "status": "New"},
    {"id": "#2", "table": "Takeaway", "items": "American Breakfast ×1, Special Breakfast ×1", "status": "New"},
    {"id": "#1", "table": "Table 2", "items": "French Toast ×1, Plain Toast ×2", "status": "Served"},
]
HERO_DISHES = [
    {"name": "Plain Toast", "price": "Rs 100"},
    {"name": "Cheese Toast", "price": "Rs 180"},
    {"name": "French Toast", "price": "Rs 210"},
]
BUILDER_ITEMS = [
    {"name": "Black Tea", "price": "Rs 40"},
    {"name": "Masala Tea", "price": "Rs 70"},
    {"name": "Milk Coffee", "price": "Rs 90"},
    {"name": "Hot Chocolate", "price": "Rs 210"},
]
STEPS = [
    {"n": "1", "title": "Build your menu", "body": "Pick dishes from the template library, set prices, add photos. Organize into categories your guests will actually browse."},
    {"n": "2", "title": "Print your QRs", "body": "Generate one code for the counter or a numbered code per table. Download the whole set as a print-ready PDF."},
    {"n": "3", "title": "Receive orders", "body": "Guests scan, browse, and order from their own phone. Orders appear in your live queue the moment they're placed."},
]
BRANCHES = [
    {"initials": "CZ", "name": "Chill Zone — Lakeside", "prefix": "chillzone", "orders": "42"},
    {"initials": "CZ", "name": "Chill Zone — City Center", "prefix": "chillzone-city", "orders": "31"},
    {"initials": "TC", "name": "The Terrace Café", "prefix": "theterrace", "orders": "18"},
]
TIERS = [
    {"name": "Starter", "price": "Free", "per": "", "blurb": "For a single café getting started.", "cta": "Start free",
     "highlighted": False, "features": ["1 branch", "Up to 30 menu items", "Branded QR menu", "Venue QR code"]},
    {"name": "Pro", "price": "$29", "per": "/month", "blurb": "For busy venues taking live orders.", "cta": "Get started",
     "highlighted": True, "features": ["1 branch, unlimited items", "Live order queue", "Table QRs + PDF export", "Photos & item badges"]},
    {"name": "Business", "price": "$79", "per": "/month", "blurb": "For groups running multiple locations.", "cta": "Talk to us",
     "highlighted": False, "features": ["Unlimited branches", "Per-branch menus & QRs", "Clone menus across branches", "Priority support"]},
]
TABLE_QRS = ["1", "2", "3", "4", "5", "6", "7", "8"]


def _landing_context(**extra):
    ctx = {
        "hero_orders": HERO_ORDERS,
        "live_orders": LIVE_ORDERS,
        "hero_dishes": HERO_DISHES,
        "builder_items": BUILDER_ITEMS,
        "steps": STEPS,
        "branches": BRANCHES,
        "tiers": TIERS,
        "table_qrs": TABLE_QRS,
        "venue_types": VENUE_TYPES,
    }
    ctx.update(extra)
    return ctx


def home(request):
    return render(request, "home.html", _landing_context())


def contact(request):
    """Landing lead-capture. HTMX requests get form/success fragments;
    non-HTMX requests get the full landing page (progressive enhancement)."""
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
            error = "Please fill in your name, venue name and phone number."
            if is_htmx:
                return render(request, "marketing/_contact_form.html", {
                    "error": error, "values": values, "venue_types": VENUE_TYPES,
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
        return render(request, "marketing/_contact_form.html", {"venue_types": VENUE_TYPES})
    return redirect("/#contact")
