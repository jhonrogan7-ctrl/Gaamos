from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render


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
