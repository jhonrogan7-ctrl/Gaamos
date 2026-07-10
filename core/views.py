from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render

from .models import Lead


def healthz(request):
    return JsonResponse({"status": "ok"})


def home(request):
    return render(request, "home.html")


def service_worker(request):
    sw_path = settings.BASE_DIR / "static" / "pwa" / "sw.js"
    content = sw_path.read_text()
    response = HttpResponse(content, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    return response


VENUE_TYPES = [c[0] for c in Lead.VENUE_TYPES]


def contact(request):
    """Landing lead-capture. GET renders a blank form (HTMX "send another");
    POST validates and persists a Lead, else re-renders the form with errors."""
    if request.method == "POST":
        values = {
            "name": request.POST.get("name", "").strip(),
            "venue_name": request.POST.get("venue_name", "").strip(),
            "phone": request.POST.get("phone", "").strip(),
            "email": request.POST.get("email", "").strip(),
            "venue_type": request.POST.get("venue_type", "Café").strip() or "Café",
            "message": request.POST.get("message", "").strip(),
        }
        if not (values["name"] and values["venue_name"] and values["phone"]):
            return render(request, "marketing/_contact_form.html", {
                "error": "Please fill in your name, venue name and phone number.",
                "values": values,
                "venue_types": VENUE_TYPES,
            })
        Lead.objects.create(**values)
        return render(request, "marketing/_contact_success.html")
    return render(request, "marketing/_contact_form.html", {"venue_types": VENUE_TYPES})
