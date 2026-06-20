import json

from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from .models import Branch, Category, BranchItemPlacement, BranchMenuItem, MenuItem


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

    payload = {
        'restaurant': {
            'name': restaurant.name if restaurant else '',
            'tagline': restaurant.tagline if restaurant else '',
            'phone': restaurant.phone if restaurant else '',
            'email': restaurant.email if restaurant else '',
        },
        'branches': branches,
        'branch': {
            'name': branch.name if branch else '',
            'address': branch.address if branch else '',
            'tag': branch.tag if branch else '',
            'slug': branch.slug if branch else '',
        },
        'selected_branch': branch.slug if branch else '',
        'categories': categories,
        'dishes': dishes,
    }
    return render(request, 'menu/index.html', {'payload': payload})


@require_POST
def place_order(request):
    """Record an order: bump each item's order_count by the ordered quantity.

    Body: {"items": [{"id": <int>, "qty": <int>}, ...]}. Real order routing
    (dine-in / pickup / delivery) is deferred — this only tracks popularity.
    """
    try:
        items = json.loads(request.body or '{}').get('items', [])
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({'error': 'invalid body'}, status=400)

    if not isinstance(items, list):
        return JsonResponse({'error': 'invalid items'}, status=400)

    for entry in items:
        try:
            item_id = int(entry['id'])
            qty = int(entry['qty'])
        except (KeyError, TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        MenuItem.objects.filter(pk=item_id).update(order_count=F('order_count') + qty)

    return JsonResponse({'ok': True})


def root(request):
    """Phase 1 root dispatcher: tenant host (company resolved) → guest menu;
    reserved/apex host (no company) → core marketing/home. Full host-based
    split lands in Phase 3."""
    if getattr(request, 'company', None) is not None:
        return menu(request)
    from core.views import home as core_home
    return core_home(request)
