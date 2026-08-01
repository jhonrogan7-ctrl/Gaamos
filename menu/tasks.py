import mimetypes
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.db import transaction

from menu.models import Item, MenuScan
from menu.pipeline import (extract, find_library, intake, item_embed, normalize,
                           photo_search)


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
                                embedding=item_embed.embed_text(text), **fields)


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


@shared_task
def find_images_for_scan(scan_id):
    """Give every photo-less row on this scan an image: library first, then the
    top external hit.

    A library hit attaches an already-verified asset with no download and no
    intake — that is the library paying off. An external hit is deposited as
    `pending`, so it flows through the existing image review queue and the next
    scanned menu costs fewer API calls than this one. An item that finds nothing
    keeps its placeholder; the per-card re-roll button is the retry, which is why
    no per-item error is stored.
    """
    from django.utils.text import slugify

    scan = MenuScan.objects.get(pk=scan_id)
    source = settings.SCAN_IMAGE_SOURCE
    items = Item.objects.filter(source_scan=scan, image_asset__isnull=True,
                                status__in=('draft', 'active'))
    for item in items:
        text = f"{item.name} {item.description}".strip()
        try:
            hits = find_library.search(text)
        except Exception:
            hits = []
        if hits:
            item.image_asset_id = hits[0]['asset_id']
            item.save(update_fields=['image_asset'])
            continue
        try:
            results = photo_search.search(source, item.name, limit=5)
            if not results:
                continue
            webp = photo_search.fetch_thumbnail(source, results[0]['url'])
        except Exception:
            continue          # one dead URL must not cost the scan its images
        asset = intake.record(source=source, webp_bytes=webp, item_name=item.name,
                              found_for_slug=slugify(item.name),
                              origin_url=results[0].get('page') or results[0]['url'],
                              tags=item.tags)
        if asset is None:
            continue          # rejected tombstone — never re-ingest a bad source
        item.image_asset = asset
        item.save(update_fields=['image_asset'])


@shared_task
def send_order_push(order_id):
    """Notify dashboard staff that a new order landed.

    Runs off the request: delivery makes a network call per subscription to an
    external push service, and the guest pressing "place order" must not wait
    on it. An order that has since been deleted is a no-op, not an error.
    """
    from menu.models import Order
    from menu.push import notify_new_order

    order = (Order.all_objects
             .filter(pk=order_id)
             .prefetch_related('items')
             .first())
    if order is None:
        return 'gone'
    t = notify_new_order(order)
    return f"sent={t['sent']} failed={t['failed']} dropped={t['dropped']}"
