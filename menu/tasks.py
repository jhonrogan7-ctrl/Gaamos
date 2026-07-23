import mimetypes
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.db import transaction

from menu.models import Item, MenuScan
from menu.pipeline import embed, extract, normalize


@shared_task
def ping():
    return "pong"


def _write_drafts(scan, payload):
    """Replace this scan's drafts with freshly normalized rows.

    Idempotent by design: only `draft` rows are deleted, so re-running a scan
    never destroys a row a human already approved, merged or rejected. Atomic
    because the rewrite calls the embedding API once per row — a failure halfway
    through must leave the previous drafts standing, not a fragment of the new set.
    """
    with transaction.atomic():
        Item.objects.filter(source_scan=scan, status="draft").delete()
        page_types = normalize.page_type_map(payload)
        for raw in payload.get("items", []):
            fields = normalize.normalize_item(raw, page_types)
            text = f"{fields['name']} {fields['description']}".strip()
            Item.objects.create(source_scan=scan, status="draft",
                                embedding=embed.embed(text), **fields)


@shared_task
def extract_menu_scan(scan_id):
    scan = MenuScan.objects.get(pk=scan_id)
    scan.status = "processing"
    scan.save(update_fields=["status"])
    try:
        path = Path(settings.MEDIA_ROOT) / scan.file
        mime = mimetypes.guess_type(scan.file)[0] or "application/pdf"
        data = extract.extract_menu(path.read_bytes(), mime)
        _write_drafts(scan, data)
        scan.raw_extraction = data
        scan.status = "extracted"
        scan.error = ""
        scan.save(update_fields=["raw_extraction", "status", "error"])
    except Exception as exc:  # noqa: BLE001 — record any failure for staff
        scan.status = "failed"
        scan.error = str(exc)
        scan.save(update_fields=["status", "error"])
