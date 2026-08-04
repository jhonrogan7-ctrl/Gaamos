import mimetypes
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.db import transaction

from menu.models import Item, MenuBuild, MenuBuildRow, MenuScan
from menu.pipeline import (extract, extract_nv, find_library, generate_flux,
                           images, intake, item_embed, normalize,
                           photo_search, throttle)


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


# Maps to the MODULE, not to the function: `extract_nv.extract_menu` looked up
# once here would be captured at import, and a test patching the module
# attribute would silently keep calling the real adapter. The attribute is read
# at call time instead.
_BACKENDS = {'nvidia': extract_nv, 'gemini': extract}


def extraction_backend():
    """The configured vision adapter.

    Both are kept on purpose: NVIDIA is the live key, and `extract.py` remains
    the prompt's home and the way back if that reverses. Rasterizing lives
    inside the NVIDIA adapter, so this seam stays a plain swap.
    """
    name = getattr(settings, 'MENU_EXTRACT_BACKEND', 'nvidia')
    try:
        module = _BACKENDS[name]
    except KeyError:
        raise ValueError(
            f'MENU_EXTRACT_BACKEND={name!r} is not one of {sorted(_BACKENDS)}')
    return module.extract_menu


@shared_task
def extract_menu_scan(scan_id):
    scan = MenuScan.objects.get(pk=scan_id)
    scan.status = "processing"
    scan.save(update_fields=["status"])
    try:
        path = Path(settings.MEDIA_ROOT) / scan.file
        mime = mimetypes.guess_type(scan.file)[0] or "application/pdf"
        data = extraction_backend()(path.read_bytes(), mime)
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


@shared_task
def generate_row_image(row_id, attempt=0):
    """Generate one build row's photograph. One row, one job.

    Per row rather than per build because the image budget is 6 a minute: a
    110-row card is 18+ minutes of wall clock, and a single looping task starts
    again from nothing every time the worker restarts -- which it does, since
    Celery has no autoreload. Independent jobs are resumable, let the shared
    throttle order the queue, and are what lets the review screen fill in
    progressively instead of showing a spinner for a third of an hour.

    Never raises. A dead generation costs its own row and nothing else; the
    reviewer sees the failure and re-rolls it by hand, which is the same
    control they use on a picture that is merely wrong.
    """
    row = MenuBuildRow.objects.filter(pk=row_id).first()
    if row is None:
        return
    row.image_state = 'generating'
    row.image_error = ''
    row.save(update_fields=['image_state', 'image_error'])

    def fail(message):
        row.image_state = 'failed'
        row.image_error = message[:300]
        row.save(update_fields=['image_state', 'image_error'])
        _finish_generating(row.build_id)

    # One budget for the image model, shared with every other caller.
    throttle.acquire(settings.NVIDIA_IMAGE_MODEL)
    try:
        seed = generate_flux.seed_for(f'{row.build_id}-{row.pk}', attempt)
        raw = generate_flux.generate_image(row.image_prompt, seed=seed)
        webp = images.to_webp(raw)
    except generate_flux.ContentFiltered as exc:
        # Not retryable at any seed. Reword the prompt by hand instead.
        return fail(f'The generator refused this prompt: {exc}')
    except Exception as exc:                      # noqa: BLE001 — see docstring
        return fail(f'{type(exc).__name__}: {exc}')

    asset = intake.record(
        source='flux', webp_bytes=webp, item_name=row.name,
        found_for_slug=f'build-{row.build_id}-{row.pk}',
        source_text=row.description, prompt=row.image_prompt, name=row.name)
    if asset is None:
        # `record` returns None only for a rejected tombstone: this exact image
        # was reviewed and thrown out before. A re-roll gets a new seed.
        return fail('This image was rejected before — re-roll for a new one.')

    row.image_asset = asset
    row.image_state = 'generated'
    row.image_error = ''
    row.save(update_fields=['image_asset', 'image_state', 'image_error'])
    _finish_generating(row.build_id)


def _finish_generating(build_id):
    """Move the build to review once no row is still waiting on a picture."""
    build = MenuBuild.objects.filter(pk=build_id).first()
    if build is None or build.status != 'generating':
        return
    if build.rows.filter(image_state__in=('none', 'generating')).exists():
        return
    build.status = 'review'
    build.save(update_fields=['status'])
