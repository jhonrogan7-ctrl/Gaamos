import mimetypes
from pathlib import Path

from celery import shared_task
from django.conf import settings

from menu.models import MenuScan
from menu.pipeline import extract


@shared_task
def ping():
    return "pong"


@shared_task
def extract_menu_scan(scan_id):
    scan = MenuScan.objects.get(pk=scan_id)
    scan.status = "processing"
    scan.save(update_fields=["status"])
    try:
        path = Path(settings.MEDIA_ROOT) / scan.file
        mime = mimetypes.guess_type(scan.file)[0] or "application/pdf"
        data = extract.extract_menu(path.read_bytes(), mime)
        scan.raw_extraction = data
        scan.status = "extracted"
        scan.error = ""
        scan.save(update_fields=["raw_extraction", "status", "error"])
    except Exception as exc:  # noqa: BLE001 — record any failure for staff
        scan.status = "failed"
        scan.error = str(exc)
        scan.save(update_fields=["status", "error"])
