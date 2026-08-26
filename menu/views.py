import json
import logging

from django.conf import settings
from django.core.cache import cache
from django.db.models import F
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from .guest_sessions import COOKIE, attach_cookie, get_or_create_session
from .models import Branch, BranchAd, BranchVisit, Category, BranchItemPlacement, BranchMenuItem, GuestSession, MenuItem, Table, Order, OrderItem, Company
from .otp import issue_code, verify_code
from .socials import social_link
from .themes import DEFAULT_THEME, THEMES

logger = logging.getLogger(__name__)


@ensure_csrf_cookie
def menu(request):
    restaurant = request.company
    branches = list(
        Branch.objects.all().values('name', 'address', 'tag', 'slug')
    ) if restaurant else []

    branch_slug = request.GET.get('branch', '')
    branch = None
    if branch_slug:
        branch = Branch.objects.filter(slug=branch_slug).first()
    if branch is None:
        branch = Branch.objects.first()

    table = None
    table_code = request.GET.get('t', '')
    if table_code:
        table = Table.objects.filter(code=table_code).first()
        if table is not None:
            branch = table.branch

    categories = []
    dishes = []
    if branch:
        bc_order = {bc.category_id: bc.display_order
                    for bc in branch.branch_categories.all()}
        bsc_order = {bsc.sub_category_id: bsc.display_order
                     for bsc in branch.branch_subcategories.select_related('sub_category')}
        cats = (Category.objects
                .filter(id__in=bc_order.keys())
                .prefetch_related('subcategories'))
        for cat in sorted(cats, key=lambda c: bc_order[c.id]):
            subs = [s for s in cat.subcategories.all() if s.id in bsc_order]
            subs.sort(key=lambda s: bsc_order[s.id])
            categories.append({
                'id': cat.slug,
                'name': cat.name,
                'icon_key': cat.icon_key,
                'hours_note': cat.hours_note,
                'subcategories': [{'name': s.name, 'icon_key': s.icon_key} for s in subs],
            })

        price_map = {bmi.menu_item_id: bmi.price_override
                     for bmi in branch.branch_items.all()}
        placements = (BranchItemPlacement.objects
                      .filter(branch=branch)
                      .select_related('menu_item', 'category', 'sub_category')
                      .order_by('display_order'))
        for pl in placements:
            item = pl.menu_item
            override = price_map.get(item.id)
            dishes.append({
                'id': item.id,
                'name': item.name,
                'description': item.description,
                'price': override if override is not None else item.price,
                'dietary_tags': item.dietary_tags,
                'image_url': item.image_url,
                'focal_x': item.focal_x,
                'focal_y': item.focal_y,
                'is_popular': item.is_popular,
                'is_featured': item.is_featured,
                'orders': item.order_count,
                'cat': pl.category.slug,
                'sub': pl.sub_category.name if pl.sub_category else '',
            })

    ad = None
    if branch:
        branch_ad = (BranchAd.objects
                     .filter(branch=branch, is_active=True)
                     .exclude(image_url='')
                     .first())
        if branch_ad:
            ad = {'image_url': branch_ad.image_url,
                  'version': int(branch_ad.updated_at.timestamp())}

    valid_layouts = {k for k, _ in Company.MENU_LAYOUT_CHOICES}
    requested = request.GET.get('layout', '')
    layout = requested if requested in valid_layouts else (
        restaurant.menu_layout if restaurant else 'baseline')

    requested_theme = request.GET.get('theme', '')
    if requested_theme in THEMES:
        theme = requested_theme
    elif branch is not None and branch.menu_theme in THEMES:
        theme = branch.menu_theme
    elif restaurant is not None and restaurant.menu_theme in THEMES:
        theme = restaurant.menu_theme
    else:
        theme = DEFAULT_THEME

    payload = {
        'restaurant': {
            'name': restaurant.name if restaurant else '',
            'tagline': restaurant.tagline if restaurant else '',
            'phone': restaurant.phone if restaurant else '',
            'email': restaurant.email if restaurant else '',
            'logo_url': restaurant.logo_url if restaurant else '',
            # None for a network the venue left empty — the contact sheet
            # branches on presence, so an unset network renders no row at all.
            'instagram': social_link('instagram', restaurant.instagram) if restaurant else None,
            'facebook': social_link('facebook', restaurant.facebook) if restaurant else None,
            'tiktok': social_link('tiktok', restaurant.tiktok) if restaurant else None,
        },
        'branches': branches,
        'branch': {
            'name': branch.name if branch else '',
            'address': branch.address if branch else '',
            'tag': branch.tag if branch else '',
            'slug': branch.slug if branch else '',
        },
        'selected_branch': branch.slug if branch else '',
        'table': {'code': table.code, 'label': table.label} if table else None,
        'categories': categories,
        'dishes': dishes,
        'layout': layout,
    }
    if branch is not None:
        BranchVisit.objects.create(branch=branch)

    return render(request, 'menu/index.html',
                  {'payload': payload, 'ad': ad, 'theme': theme})


def _queue_order_push(order_id):
    """Hand the new order to the worker for push delivery.

    Swallows everything. The broker being down, or Celery not running at all,
    must never turn a guest's successful order into an error — the order is
    already committed and the dashboard queue still shows it.
    """
    try:
        from .tasks import send_order_push
        send_order_push.delay(order_id)
    except Exception:                                    # noqa: BLE001
        logger.exception('could not queue order push for order=%s', order_id)


@require_POST
def place_order(request):
    """Create a real Order for the active tenant. Body:
    {branch:<slug>, table:<code?>, items:[{id,qty}]}. Branch/table/items are
    resolved only within request.company (fail-closed). Still bumps order_count.
    """
    try:
        body = json.loads(request.body or '{}')
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({'error': 'invalid body'}, status=400)

    raw_items = body.get('items', [])
    if not isinstance(raw_items, list) or not raw_items:
        return JsonResponse({'error': 'no items'}, status=400)

    branch = Branch.objects.filter(slug=body.get('branch', '')).first()
    if branch is None:
        branch = Branch.objects.first()
    if branch is None:
        return JsonResponse({'error': 'no branch'}, status=400)

    table = None
    if body.get('table'):
        table = Table.objects.filter(code=body['table'], branch=branch).first()

    gs, token, _ = get_or_create_session(request, branch, table)

    lines, total = [], 0
    for entry in raw_items:
        try:
            item_id = int(entry['id'])
            qty = int(entry['qty'])
        except (KeyError, TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        # MenuItem.objects is the fail-closed TenantManager: only this tenant's items.
        item = MenuItem.objects.filter(pk=item_id).first()
        if item is None:
            continue
        lines.append((item, qty))
        total += item.price * qty

    if not lines:
        return JsonResponse({'error': 'no valid items'}, status=400)

    order = Order.objects.create(
        branch=branch, table=table,
        table_label=table.label if table else '',
        total=total, guest_session=gs,
    )
    for item, qty in lines:
        OrderItem.objects.create(order=order, menu_item=item,
                                 name=item.name, unit_price=item.price, qty=qty)
        MenuItem.objects.filter(pk=item.pk).update(order_count=F('order_count') + qty)

    _queue_order_push(order.pk)
    resp = JsonResponse({'ok': True, 'number': order.number})
    return attach_cookie(resp, token)


def _resolve_active_session(request):
    """The active GuestSession for this browser, or None.

    Mirrors the cookie contract from menu/guest_sessions.py without going
    through get_or_create_session: these endpoints act on a session that must
    already exist (created by place_order) — a missing/invalid/stale cookie
    means there is nothing to attach identity or OTP to, which is a client
    error, not a fresh session to silently create.

    menu/urls.py is mounted globally, so this can be reached on an apex/
    reserved/unknown host where TenantMiddleware sets request.company = None.
    GuestSession.objects is the fail-closed TenantManager: querying it with no
    company in context raises TenantContextRequired rather than returning no
    rows. Guarding on request.company here — before the query — turns that
    into the same 400 the caller already gets for a missing/invalid cookie,
    never an uncaught 500."""
    if getattr(request, 'company', None) is None:
        return None
    token = request.COOKIES.get(COOKIE, '')
    if not token:
        return None
    return GuestSession.objects.filter(token=token, closed_at__isnull=True).first()


def _queue_otp_sms(phone, code):
    """Hand the OTP text to the worker for delivery. Swallows everything, same
    as _queue_order_push above: the code was already written to the DB by
    issue_code() before this is called, so a dead broker costs the guest an
    SMS, never the ability to be verified."""
    try:
        from .tasks import send_otp_sms
        send_otp_sms.delay(phone, code)
    except Exception:                                    # noqa: BLE001
        logger.exception('could not queue otp sms for phone=%s', phone)


@require_POST
def identity_submit(request):
    """Guest identity capture. Body: {name, phone?}. Branches on
    request.company.identity_mode: name/room/auto save straight to the
    session (no OTP); phone issues a code and enqueues its SMS."""
    gs = _resolve_active_session(request)
    if gs is None:
        return JsonResponse({'error': 'no active session'}, status=400)

    try:
        body = json.loads(request.body or '{}')
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({'error': 'invalid body'}, status=400)

    name = (body.get('name') or '').strip()
    phone = (body.get('phone') or '').strip()
    mode = request.company.identity_mode

    if mode == 'phone':
        if not phone:
            return JsonResponse({'error': 'phone required'}, status=400)
        if name:
            gs.name = name
            gs.save(update_fields=['name'])
        code = issue_code(gs, phone)
        _queue_otp_sms(phone, code)
        return JsonResponse({'ok': True, 'otp': True})

    update_fields = []
    if name:
        gs.name = name
        update_fields.append('name')
    if phone:
        gs.contact = phone
        update_fields.append('contact')
    if update_fields:
        gs.save(update_fields=update_fields)
    return JsonResponse({'ok': True})


@require_POST
def otp_verify(request):
    """Verify a submitted OTP code against the active session. Body: {code}."""
    gs = _resolve_active_session(request)
    if gs is None:
        return JsonResponse({'error': 'no active session'}, status=400)

    try:
        body = json.loads(request.body or '{}')
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({'error': 'invalid body'}, status=400)

    ok = verify_code(gs, str(body.get('code', '')))
    return JsonResponse({'ok': ok, 'verified': gs.verified})


@require_POST
def otp_resend(request):
    """Re-issue and re-send an OTP code for the active session's phone.

    Rate-limited by reusing the same GUEST_RATE_LIMIT/GUEST_RATE_WINDOW knobs
    RateLimitMiddleware already uses for guest reads (see menu/middleware.py),
    keyed per-session rather than per-IP so one guest resending repeatedly
    can't be masked by (or itself trip) the shared IP counter."""
    gs = _resolve_active_session(request)
    if gs is None:
        return JsonResponse({'error': 'no active session'}, status=400)

    last = gs.otp_challenges.order_by('-id').first()
    phone = last.phone if last else gs.contact
    if not phone:
        return JsonResponse({'error': 'no phone on file'}, status=400)

    limit = getattr(settings, 'GUEST_RATE_LIMIT', 120)
    window = getattr(settings, 'GUEST_RATE_WINDOW', 60)
    key = f'otp-resend:{gs.pk}'
    cache.add(key, 0, window)
    count = cache.incr(key)
    if count > limit:
        return HttpResponse('Too Many Requests', status=429)

    code = issue_code(gs, phone)
    _queue_otp_sms(phone, code)
    return JsonResponse({'ok': True})


@ensure_csrf_cookie
def root(request):
    """Root dispatcher: tenant host (company resolved) → guest menu;
    apex/reserved host → redirect to the language-prefixed marketing landing
    (LocaleMiddleware has already negotiated Accept-Language, fallback en)."""
    if getattr(request, 'company', None) is not None:
        return menu(request)
    from django.utils import translation
    return redirect(f"/{translation.get_language() or 'en'}/")
