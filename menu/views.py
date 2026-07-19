import json

from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from .models import Branch, BranchAd, Category, BranchItemPlacement, BranchMenuItem, MenuItem, Table, Order, OrderItem, Company
from .themes import DEFAULT_THEME, THEMES


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
    return render(request, 'menu/index.html',
                  {'payload': payload, 'ad': ad, 'theme': theme})


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
        total=total,
    )
    for item, qty in lines:
        OrderItem.objects.create(order=order, menu_item=item,
                                 name=item.name, unit_price=item.price, qty=qty)
        MenuItem.objects.filter(pk=item.pk).update(order_count=F('order_count') + qty)

    return JsonResponse({'ok': True, 'number': order.number})


@ensure_csrf_cookie
def root(request):
    """Root dispatcher: tenant host (company resolved) → guest menu;
    apex/reserved host → redirect to the language-prefixed marketing landing
    (LocaleMiddleware has already negotiated Accept-Language, fallback en)."""
    if getattr(request, 'company', None) is not None:
        return menu(request)
    from django.utils import translation
    return redirect(f"/{translation.get_language() or 'en'}/")
