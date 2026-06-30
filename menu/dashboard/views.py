import json
import os

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.conf import settings as django_settings

from django.db import models
from menu.models import (
    Company, Branch, Category, SubCategory, MenuItem, BranchMenuItem,
    BranchCategory, BranchSubCategory, BranchItemPlacement, Membership, Table,
)
from menu.permissions import (
    require_membership, require_owner, ensure_can_manage_branch, forbidden,
)
from menu.imaging import compute_focal_point

ALLOWED_IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp')
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def save_item_image(item, upload):
    """Persist an uploaded image for ``item`` and auto-compute its focal point.

    Returns the public media URL on success, or None if the upload was rejected
    (bad extension / too large). Used by both the full item-edit form and the
    inline image-upload endpoint so the storage + saliency logic lives once.
    """
    ext = os.path.splitext(upload.name)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTS or upload.size > MAX_IMAGE_BYTES:
        return None
    dest_dir = os.path.join(django_settings.MEDIA_ROOT, 'items')
    os.makedirs(dest_dir, exist_ok=True)
    filename = f"item_{item.pk}{ext}"
    path = os.path.join(dest_dir, filename)
    with open(path, 'wb') as f:
        for chunk in upload.chunks():
            f.write(chunk)
    item.image_url = f"{django_settings.MEDIA_URL}items/{filename}"
    item.focal_x, item.focal_y = compute_focal_point(path)
    item.save(update_fields=['image_url', 'focal_x', 'focal_y'])
    return item.image_url


def login_view(request):
    error = ''
    if request.method == 'POST':
        username = request.POST.get('username', '')
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is None:
            error = 'Access denied'
        elif user.is_superuser or Membership.objects.filter(
                user=user, company=request.company).exists():
            login(request, user)
            return redirect('dashboard:home')
        else:
            error = 'Access denied'
    return render(request, 'dashboard/login.html', {'error': error})


@require_POST
def logout_view(request):
    logout(request)
    return redirect('dashboard:login')


@require_membership
def overview(request):
    return render(request, 'dashboard/overview.html', {'active_tab': 'overview'})


@require_membership
def orders(request):
    return render(request, 'dashboard/orders.html', {'active_tab': 'orders'})


@require_membership
def branches(request):
    m = request.membership
    if request.user.is_superuser or (m and m.is_owner):
        qs = Branch.objects.all()
    elif m:
        qs = Branch.objects.filter(pk__in=m.branches.values_list('pk', flat=True))
    else:
        qs = Branch.objects.none()
    return render(request, 'dashboard/branches.html', {'active_tab': 'branches', 'branches': qs})


@require_membership
def home(request):
    restaurant = request.company
    total_count = MenuItem.objects.count()
    m = request.membership
    if request.user.is_superuser or (m and m.is_owner):
        branches = Branch.objects.all()
    elif m:
        branches = Branch.objects.filter(pk__in=m.branches.values_list('pk', flat=True))
    else:
        branches = Branch.objects.none()
    branches_data = []
    for branch in branches:
        active_count = (BranchItemPlacement.objects
                        .filter(branch=branch).values('menu_item').distinct().count())
        pct = round(active_count / total_count * 100) if total_count else 0
        branches_data.append({
            'obj': branch,
            'active_count': active_count,
            'total_count': total_count,
            'pct': pct,
        })
    return render(request, 'dashboard/home.html', {
        'active_tab': 'home',
        'restaurant': restaurant,
        'branches_data': branches_data,
    })


# value -> (label, order_by).
ITEM_SORTS = {
    '':           ('Name A–Z',          'name'),
    'name_desc':  ('Name Z–A',          '-name'),
    'price_asc':  ('Price: low → high', 'price'),
    'price_desc': ('Price: high → low', '-price'),
    'orders':     ('Most ordered',      '-order_count'),
}


@require_owner
def items_list(request):
    search = request.GET.get('q', '')
    diet_filter = request.GET.get('diet', '')
    flag_filter = request.GET.get('flag', '')
    price_min_raw = request.GET.get('price_min', '')
    price_max_raw = request.GET.get('price_max', '')
    sort = request.GET.get('sort', '')
    if sort not in ITEM_SORTS:
        sort = ''

    items = MenuItem.objects.all()

    if search:
        items = items.filter(name__icontains=search)
    if flag_filter == 'popular':
        items = items.filter(is_popular=True)
    elif flag_filter == 'featured':
        items = items.filter(is_featured=True)

    def _to_int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    price_min, price_max = _to_int(price_min_raw), _to_int(price_max_raw)
    if price_min is not None:
        items = items.filter(price__gte=price_min)
    if price_max is not None:
        items = items.filter(price__lte=price_max)

    items = items.order_by(ITEM_SORTS[sort][1], 'name')

    items = list(items)
    # JSONField __contains isn't supported on SQLite, so filter dietary tags in Python.
    if diet_filter:
        items = [m for m in items if diet_filter in (m.dietary_tags or [])]

    # Distinct dietary tags actually present, for the filter pills.
    diet_options = sorted({t for m in MenuItem.objects.values_list('dietary_tags', flat=True)
                           for t in (m or [])})

    active_filter_count = sum([
        bool(diet_filter), bool(flag_filter), bool(price_min_raw or price_max_raw),
    ])

    # Real categories shown as builder structure. Item→category placement is
    # per-branch (BranchItemPlacement); the company dashboard has no branch context,
    # so categories render as structure and items as a flat re-usable library.
    categories = Category.objects.prefetch_related('subcategories').order_by('display_order')

    return render(request, 'dashboard/items/list.html', {
        'active_tab': 'items',
        'items': items,
        'categories': categories,
        'diet_options': diet_options,
        'sort_options': [(val, label) for val, (label, _) in ITEM_SORTS.items()],
        'result_count': len(items),
        'search': search,
        'diet_filter': diet_filter,
        'flag_filter': flag_filter,
        'price_min_raw': price_min_raw,
        'price_max_raw': price_max_raw,
        'sort': sort,
        'active_filter_count': active_filter_count,
    })


@require_owner
def item_edit(request, pk=None):
    from .forms import MenuItemForm
    item = get_object_or_404(MenuItem, pk=pk) if pk else None
    if request.method == 'POST':
        form = MenuItemForm(request.POST, instance=item)
        if form.is_valid():
            saved = form.save()
            # Handle file upload — takes priority over URL field. This also
            # auto-computes a focal point from the new image.
            upload = request.FILES.get('image_file')
            if upload:
                save_item_image(saved, upload)
            # Manual focal-point override from the dashboard picker. Applied
            # after upload so a deliberate nudge wins over the auto guess.
            fx, fy = request.POST.get('focal_x'), request.POST.get('focal_y')
            if fx and fy:
                try:
                    saved.focal_x = max(0, min(100, int(fx)))
                    saved.focal_y = max(0, min(100, int(fy)))
                    saved.save(update_fields=['focal_x', 'focal_y'])
                except (TypeError, ValueError):
                    pass
            return redirect('dashboard:items_list')
    else:
        form = MenuItemForm(instance=item)

    return render(request, 'dashboard/items/edit.html', {
        'active_tab': 'items',
        'form': form,
        'item': item,
        'dietary_choices': ['VEG', 'VEGAN', 'HALAL', 'GF', 'SPICY'],
    })


@require_owner
@require_POST
def item_delete(request, pk):
    item = get_object_or_404(MenuItem, pk=pk)
    item.delete()
    return redirect('dashboard:items_list')


@require_owner
@require_POST
def item_image_upload(request, pk):
    item = get_object_or_404(MenuItem, pk=pk)
    upload = request.FILES.get('image')
    if not upload:
        return JsonResponse({'error': 'No file'}, status=400)
    ext = os.path.splitext(upload.name)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        return JsonResponse({'error': 'Invalid file type'}, status=400)
    if upload.size > MAX_IMAGE_BYTES:
        return JsonResponse({'error': 'File too large (max 5 MB)'}, status=400)
    url = save_item_image(item, upload)
    return JsonResponse({'url': url, 'focal_x': item.focal_x, 'focal_y': item.focal_y})


@require_owner
def categories_index(request):
    categories = Category.objects.prefetch_related('subcategories').order_by('display_order')
    cats_data = []
    for cat in categories:
        subs_data = [{'obj': sub} for sub in cat.subcategories.all()]
        cats_data.append({'obj': cat, 'subs': subs_data})
    return render(request, 'dashboard/categories/index.html', {
        'active_tab': 'categories',
        'cats_data': cats_data,
        'icon_choices': [
            # Category-level
            'brunch', 'bowl', 'special', 'juice', 'dinner', 'bar', 'hookah', 'dessert',
            'coffee', 'smoothie', 'snack', 'pizza', 'noodles', 'cake', 'meat', 'rice',
            # Subcategory — food
            'subAll', 'subEggs', 'subToast', 'subPoke', 'subSalad', 'subBurger',
            'subSandwich', 'subWrap', 'subPasta', 'subPizza', 'subSoup', 'subMains',
            'subNoodle', 'subEntree',
            # Subcategory — drinks
            'subCoffee', 'subTea', 'subKombucha', 'subSmoothie', 'subJuice', 'subBucket',
            'subFrappe', 'subBubbleTea', 'subMocktail', 'subSoda', 'subShot',
            # Subcategory — bar
            'subCocktail', 'subWarm', 'subBeer', 'subTapBeer', 'subSpirits', 'subWine', 'subSparkle',
        ],
    })


@require_owner
@require_POST
def category_save(request, pk=None):
    from django.utils.text import slugify
    cat = get_object_or_404(Category, pk=pk) if pk else None
    name = request.POST.get('name', '').strip()
    icon_key = request.POST.get('icon_key', '').strip()
    hours_note = request.POST.get('hours_note', '').strip()
    if not name:
        return redirect('dashboard:categories')
    if cat:
        cat.name = name
        cat.icon_key = icon_key
        cat.hours_note = hours_note
        cat.save()
    else:
        base = slugify(name)
        slug = base
        counter = 1
        while Category.objects.filter(slug=slug).exists():
            slug = f"{base}-{counter}"
            counter += 1
        Category.objects.create(name=name, slug=slug, icon_key=icon_key,
                                hours_note=hours_note, display_order=Category.objects.count())
    return redirect('dashboard:categories')


@require_owner
@require_POST
def category_delete(request, pk):
    cat = get_object_or_404(Category, pk=pk)
    if BranchItemPlacement.objects.filter(category=cat).exists():
        return JsonResponse({'ok': False, 'error': 'In use by a branch menu. Remove it there first.'})
    cat.delete()
    return JsonResponse({'ok': True})


@require_owner
@require_POST
def subcategory_save(request, pk=None):
    sub = get_object_or_404(SubCategory, pk=pk) if pk else None
    name = request.POST.get('name', '').strip()
    icon_key = request.POST.get('icon_key', 'subAll').strip()
    cat_id = request.POST.get('category')
    if not name:
        return redirect('dashboard:categories')
    if sub:
        sub.name = name
        sub.icon_key = icon_key
        sub.save()
    else:
        cat = get_object_or_404(Category, pk=cat_id)
        SubCategory.objects.create(
            category=cat, name=name, icon_key=icon_key,
            display_order=SubCategory.objects.filter(category=cat).count()
        )
    return redirect('dashboard:categories')


@require_owner
@require_POST
def subcategory_delete(request, pk):
    sub = get_object_or_404(SubCategory, pk=pk)
    if BranchItemPlacement.objects.filter(sub_category=sub).exists():
        return JsonResponse({'ok': False, 'error': 'In use by a branch menu. Remove it there first.'})
    sub.delete()
    return JsonResponse({'ok': True})


@require_membership
def qr_index(request):
    # TenantManager scopes this to request.company automatically
    branches = Branch.objects.all()
    return render(request, 'dashboard/qr/index.html', {
        'active_tab': 'qr',
        'branches': branches,
    })


@require_membership
@require_POST
def qr_generate(request, branch_id):
    from .utils import generate_qr_for_branch
    branch = get_object_or_404(Branch, pk=branch_id)
    if not ensure_can_manage_branch(request, branch):
        return forbidden(request)
    generate_qr_for_branch(branch)
    return redirect('dashboard:qr')


@require_membership
def qr_download(request, branch_id):
    from django.http import HttpResponse
    from .utils import generate_qr_pdf
    branch = get_object_or_404(Branch, pk=branch_id)
    if not ensure_can_manage_branch(request, branch):
        return forbidden(request)
    if not branch.qr_image:
        return HttpResponse('QR not yet generated for this branch', status=404)
    fmt = request.GET.get('format', 'png')
    if fmt == 'pdf':
        pdf_bytes = generate_qr_pdf(branch)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="qr-{branch.slug}.pdf"'
        return response
    else:
        import os
        from django.conf import settings as django_settings
        path = os.path.join(django_settings.MEDIA_ROOT, branch.qr_image)
        with open(path, 'rb') as f:
            response = HttpResponse(f.read(), content_type='image/png')
        response['Content-Disposition'] = f'attachment; filename="qr-{branch.slug}.png"'
        return response


@require_owner
def settings_index(request):
    restaurant = request.company
    branches = Branch.objects.all()
    members = Membership.objects.filter(company=request.company).select_related('user').prefetch_related('branches')
    return render(request, 'dashboard/settings/index.html', {
        'active_tab': 'settings',
        'restaurant': restaurant,
        'branches': branches,
        'members': members,
    })


@require_owner
@require_POST
def settings_restaurant(request):
    restaurant = request.company
    restaurant.name = request.POST.get('name', '').strip()
    restaurant.tagline = request.POST.get('tagline', '').strip()
    restaurant.phone = request.POST.get('phone', '').strip()
    restaurant.email = request.POST.get('email', '').strip()
    restaurant.instagram = request.POST.get('instagram', '').strip()
    restaurant.facebook = request.POST.get('facebook', '').strip()
    restaurant.tiktok = request.POST.get('tiktok', '').strip()
    restaurant.save()
    return redirect('dashboard:settings')


@require_owner
@require_POST
def branch_save(request, pk=None):
    from django.utils.text import slugify
    branch = get_object_or_404(Branch, pk=pk) if pk else None
    name = request.POST.get('name', '').strip()
    address = request.POST.get('address', '').strip()
    tag = request.POST.get('tag', '').strip()
    if not name:
        return redirect('dashboard:settings')
    if branch:
        branch.name = name
        branch.address = address
        branch.tag = tag
        branch.save()
    else:
        base = slugify(name)
        slug = base
        counter = 1
        while Branch.objects.filter(slug=slug).exists():
            slug = f"{base}-{counter}"
            counter += 1
        Branch.objects.create(company=request.company, name=name, slug=slug, address=address, tag=tag)
    return redirect('dashboard:settings')


@require_owner
@require_POST
def branch_delete(request, pk):
    branch = get_object_or_404(Branch, pk=pk)
    if Branch.objects.count() <= 1:
        return JsonResponse({'ok': False, 'error': 'Cannot delete the only branch.'})
    branch.delete()
    return JsonResponse({'ok': True})


@require_owner
@require_POST
def member_save(request, pk=None):
    from django.contrib.auth.models import User as DjangoUser
    role = request.POST.get('role', Membership.ROLE_MANAGER)
    role = role if role in (Membership.ROLE_OWNER, Membership.ROLE_MANAGER) else Membership.ROLE_MANAGER
    branch_ids = request.POST.getlist('branches')
    if pk:
        membership = get_object_or_404(Membership, pk=pk, company=request.company)
        # last-owner guard: block demoting the only owner
        if membership.is_owner and role != Membership.ROLE_OWNER and _is_last_owner(membership):
            return redirect('dashboard:settings')
        user = membership.user
        user.email = request.POST.get('email', user.email).strip()
        password = request.POST.get('password', '').strip()
        if password:
            user.set_password(password)
        user.save()
        membership.role = role
        membership.save()
    else:
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()
        if not (username and password):
            return redirect('dashboard:settings')
        if DjangoUser.objects.filter(username=username).exists():
            # Refuse: username is global; resetting/attaching a pre-existing account
            # here would be a cross-tenant takeover vector. (Shared-user invites = later phase.)
            return redirect('dashboard:settings')
        user = DjangoUser.objects.create_user(username=username, email=email, password=password)
        membership = Membership.objects.create(user=user, company=request.company, role=role)
    membership.branches.set(
        Branch.objects.filter(pk__in=branch_ids) if role == Membership.ROLE_MANAGER else [])
    return redirect('dashboard:settings')


@require_owner
@require_POST
def member_delete(request, pk):
    membership = get_object_or_404(Membership, pk=pk, company=request.company)
    if membership.is_owner and _is_last_owner(membership):
        return JsonResponse({'ok': False, 'error': 'Cannot remove the last owner.'})
    membership.delete()
    return JsonResponse({'ok': True})


def _is_last_owner(membership):
    return not (Membership.objects
                .filter(company=membership.company, role=Membership.ROLE_OWNER)
                .exclude(pk=membership.pk)
                .exists())


@require_membership
def api_subcategories(request):
    cat_id = request.GET.get('cat')
    subs = list(SubCategory.objects.filter(category_id=cat_id).values('id', 'name'))
    return JsonResponse({'subcategories': subs})


def _build_composition(branch):
    """Tree of categories → sub-category groups → item placements for a branch.
    Shared by the builder page (initial render) and the composition endpoint
    (re-fetched after each mutation so the UI updates without a page reload)."""
    price_map = {bmi.menu_item_id: bmi.price_override for bmi in branch.branch_items.all()}
    placement_counts = {}
    for pl in branch.placements.all():
        placement_counts[pl.menu_item_id] = placement_counts.get(pl.menu_item_id, 0) + 1

    bc = list(branch.branch_categories.select_related('category').order_by('display_order'))
    bsc = list(branch.branch_subcategories.select_related('sub_category').order_by('display_order'))
    placements = list(branch.placements.select_related('menu_item').order_by('display_order'))

    subs_by_cat = {}
    for s in bsc:
        subs_by_cat.setdefault(s.sub_category.category_id, []).append(
            {'bsc_id': s.pk, 'sub_id': s.sub_category_id, 'name': s.sub_category.name})

    def placements_for(cat_id, sub_id):
        out = []
        for pl in placements:
            if pl.category_id == cat_id and pl.sub_category_id == sub_id:
                ov = price_map.get(pl.menu_item_id)
                out.append({
                    'pl_id': pl.pk, 'item_id': pl.menu_item_id, 'name': pl.menu_item.name,
                    'image_url': pl.menu_item.image_url,
                    'price': ov if ov is not None else pl.menu_item.price,
                    'template_price': pl.menu_item.price,
                    'override': ov is not None,
                    'also_in': placement_counts.get(pl.menu_item_id, 1) - 1,
                })
        return out

    composition = []
    for c in bc:
        groups = [{'bsc_id': g['bsc_id'], 'sub_id': g['sub_id'], 'name': g['name'],
                   'items': placements_for(c.category_id, g['sub_id'])}
                  for g in subs_by_cat.get(c.category_id, [])]
        direct = placements_for(c.category_id, None)
        composition.append({'bc_id': c.pk, 'cat_id': c.category_id, 'slug': c.category.slug,
                            'name': c.category.name, 'direct': direct, 'groups': groups})
    return composition


@require_membership
def branch_composition(request, slug):
    """JSON snapshot of the branch's composition tree, re-fetched by the builder
    after each mutation to refresh in place (no full page reload)."""
    branch = get_object_or_404(Branch, slug=slug)
    if not ensure_can_manage_branch(request, branch):
        return forbidden(request)
    return JsonResponse(_build_composition(branch), safe=False)


@require_membership
def branch_items(request, slug):
    branch = get_object_or_404(Branch, slug=slug)
    if not ensure_can_manage_branch(request, branch):
        return forbidden(request)
    composition = _build_composition(branch)

    library = [{'id': m.id, 'name': m.name, 'price': m.price, 'image_url': m.image_url,
                'tags': m.dietary_tags or []} for m in MenuItem.objects.order_by('name')]
    catalog = [{'id': c.id, 'name': c.name,
                'subs': [{'id': s.id, 'name': s.name} for s in c.subcategories.all()]}
               for c in Category.objects.prefetch_related('subcategories').order_by('display_order')]

    return render(request, 'dashboard/branch/items.html', {
        'active_tab': 'branches', 'branch_tab': 'menu', 'branch': branch,
        'composition_json': json.dumps(composition),
        'library_json': json.dumps(library),
        'catalog_json': json.dumps(catalog),
        'branches_json': json.dumps(
            [{'slug': b.slug, 'name': b.name} for b in Branch.objects.exclude(pk=branch.pk)]),
    })


@require_membership
def branch_qr(request, slug):
    branch = get_object_or_404(Branch, slug=slug)
    if not ensure_can_manage_branch(request, branch):
        return forbidden(request)
    return render(request, 'dashboard/branch/qr.html', {
        'active_tab': 'branches', 'branch_tab': 'qr', 'branch': branch,
        'tables': branch.tables.all(),
    })


@require_membership
def branch_orders(request, slug):
    branch = get_object_or_404(Branch, slug=slug)
    if not ensure_can_manage_branch(request, branch):
        return forbidden(request)
    return render(request, 'dashboard/branch/orders.html', {
        'active_tab': 'branches', 'branch_tab': 'orders', 'branch': branch,
        'has_tables': branch.tables.exists(),
    })


@require_membership
@require_POST
def tables_add(request, slug):
    branch = get_object_or_404(Branch, slug=slug)
    if not ensure_can_manage_branch(request, branch):
        return forbidden(request)
    label = request.POST.get('label', '').strip()
    if label:
        Table.objects.create(branch=branch, label=label)
    return redirect('dashboard:branch_qr', slug=branch.slug)


@require_membership
@require_POST
def tables_bulk(request, slug):
    branch = get_object_or_404(Branch, slug=slug)
    if not ensure_can_manage_branch(request, branch):
        return forbidden(request)
    try:
        start = int(request.POST.get('start', ''))
        end = int(request.POST.get('end', ''))
    except ValueError:
        return redirect('dashboard:branch_qr', slug=branch.slug)
    if start <= end and (end - start + 1) <= 200:
        existing = set(Table.objects.filter(branch=branch).values_list('label', flat=True))
        for n in range(start, end + 1):
            if str(n) not in existing:
                Table.objects.create(branch=branch, label=str(n), display_order=n)
    return redirect('dashboard:branch_qr', slug=branch.slug)


@require_membership
@require_POST
def table_edit(request, slug, code):
    branch = get_object_or_404(Branch, slug=slug)
    if not ensure_can_manage_branch(request, branch):
        return forbidden(request)
    table = get_object_or_404(Table, code=code, branch=branch)
    label = request.POST.get('label', '').strip()
    if label:
        table.label = label
        table.save(update_fields=['label'])
    return redirect('dashboard:branch_qr', slug=branch.slug)


@require_membership
@require_POST
def table_delete(request, slug, code):
    branch = get_object_or_404(Branch, slug=slug)
    if not ensure_can_manage_branch(request, branch):
        return forbidden(request)
    get_object_or_404(Table, code=code, branch=branch).delete()
    return redirect('dashboard:branch_qr', slug=branch.slug)


@require_membership
def table_qr(request, slug, code):
    from django.http import HttpResponse
    from .utils import render_qr_png, table_qr_url, render_table_qr_pdf
    branch = get_object_or_404(Branch, slug=slug)
    if not ensure_can_manage_branch(request, branch):
        return forbidden(request)
    table = get_object_or_404(Table, code=code, branch=branch)
    if request.GET.get('format') == 'pdf':
        pdf = render_table_qr_pdf(branch, [table])
        resp = HttpResponse(pdf, content_type='application/pdf')
        resp['Content-Disposition'] = f'attachment; filename="qr-{branch.slug}-table-{table.code}.pdf"'
        return resp
    png = render_qr_png(table_qr_url(branch, table), f"{branch.name} — {table.label}")
    return HttpResponse(png, content_type='image/png')


@require_membership
def tables_qr_pdf(request, slug):
    from django.http import HttpResponse
    from .utils import render_table_qr_pdf
    branch = get_object_or_404(Branch, slug=slug)
    if not ensure_can_manage_branch(request, branch):
        return forbidden(request)
    pdf = render_table_qr_pdf(branch, list(branch.tables.all()))
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="qr-{branch.slug}-tables.pdf"'
    return resp


def _next_order(qs):
    return (qs.aggregate(models.Max('display_order'))['display_order__max'] or -1) + 1


@require_membership
@require_POST
def branch_category_add(request, slug):
    branch = get_object_or_404(Branch, slug=slug)
    if not ensure_can_manage_branch(request, branch):
        return forbidden(request)
    cat = get_object_or_404(Category, pk=request.POST.get('category_id'))
    bc, created = BranchCategory.objects.get_or_create(
        branch=branch, category=cat,
        defaults={'display_order': _next_order(branch.branch_categories)})
    return JsonResponse({'id': bc.pk, 'category_id': cat.pk, 'created': created})


@require_membership
@require_POST
def branch_category_remove(request, slug, pk):
    branch = get_object_or_404(Branch, slug=slug)
    if not ensure_can_manage_branch(request, branch):
        return forbidden(request)
    bc = get_object_or_404(BranchCategory, pk=pk, branch=branch)
    cat_id = bc.category_id
    BranchItemPlacement.objects.filter(branch=branch, category_id=cat_id).delete()
    BranchSubCategory.objects.filter(
        branch=branch, sub_category__category_id=cat_id).delete()
    bc.delete()
    return JsonResponse({'ok': True})


@require_membership
@require_POST
def branch_subcategory_add(request, slug):
    branch = get_object_or_404(Branch, slug=slug)
    if not ensure_can_manage_branch(request, branch):
        return forbidden(request)
    sub = get_object_or_404(SubCategory, pk=request.POST.get('sub_category_id'))
    BranchCategory.objects.get_or_create(
        branch=branch, category=sub.category,
        defaults={'display_order': _next_order(branch.branch_categories)})
    bsc, created = BranchSubCategory.objects.get_or_create(
        branch=branch, sub_category=sub,
        defaults={'display_order': _next_order(branch.branch_subcategories)})
    return JsonResponse({'id': bsc.pk, 'sub_category_id': sub.pk, 'created': created})


@require_membership
@require_POST
def branch_subcategory_remove(request, slug, pk):
    branch = get_object_or_404(Branch, slug=slug)
    if not ensure_can_manage_branch(request, branch):
        return forbidden(request)
    bsc = get_object_or_404(BranchSubCategory, pk=pk, branch=branch)
    BranchItemPlacement.objects.filter(
        branch=branch, sub_category_id=bsc.sub_category_id).delete()
    bsc.delete()
    return JsonResponse({'ok': True})


@require_membership
@require_POST
def branch_placements_add(request, slug):
    branch = get_object_or_404(Branch, slug=slug)
    if not ensure_can_manage_branch(request, branch):
        return forbidden(request)
    cat = get_object_or_404(Category, pk=request.POST.get('category_id'))
    sub_id = request.POST.get('sub_category_id') or None
    sub = get_object_or_404(SubCategory, pk=sub_id) if sub_id else None
    BranchCategory.objects.get_or_create(
        branch=branch, category=cat,
        defaults={'display_order': _next_order(branch.branch_categories)})
    if sub:
        BranchSubCategory.objects.get_or_create(
            branch=branch, sub_category=sub,
            defaults={'display_order': _next_order(branch.branch_subcategories)})
    created = []
    for raw in request.POST.getlist('item_ids'):
        try:
            item = MenuItem.objects.get(pk=int(raw))
        except (ValueError, MenuItem.DoesNotExist):
            continue
        pl, was_new = BranchItemPlacement.objects.get_or_create(
            branch=branch, menu_item=item, category=cat, sub_category=sub,
            defaults={'display_order': _next_order(branch.placements)})
        if was_new:
            created.append(pl.pk)
    return JsonResponse({'created': created})


@require_membership
@require_POST
def branch_placement_remove(request, slug, pk):
    branch = get_object_or_404(Branch, slug=slug)
    if not ensure_can_manage_branch(request, branch):
        return forbidden(request)
    get_object_or_404(BranchItemPlacement, pk=pk, branch=branch).delete()
    return JsonResponse({'ok': True})


@require_membership
@require_POST
def branch_reorder(request, slug):
    branch = get_object_or_404(Branch, slug=slug)
    if not ensure_can_manage_branch(request, branch):
        return forbidden(request)
    level = request.POST.get('level')
    model = {'category': BranchCategory, 'subcategory': BranchSubCategory,
             'placement': BranchItemPlacement}.get(level)
    if model is None:
        return JsonResponse({'error': 'bad level'}, status=400)
    ids = [int(x) for x in request.POST.get('ids', '').split(',') if x.strip().isdigit()]
    for order, pk in enumerate(ids):
        model.objects.filter(pk=pk, branch=branch).update(display_order=order)
    return JsonResponse({'ok': True})


@require_membership
@require_POST
def branch_clone(request, slug):
    target = get_object_or_404(Branch, slug=slug)
    if not ensure_can_manage_branch(request, target):
        return forbidden(request)
    source = get_object_or_404(Branch, slug=request.POST.get('source'))
    if not ensure_can_manage_branch(request, source):
        return forbidden(request)
    raw = request.POST.get('category_ids', '').strip()
    cat_ids = [int(x) for x in raw.split(',') if x.strip().isdigit()] if raw else None

    def keep_cat(cid):
        return cat_ids is None or cid in cat_ids

    # Wipe overlapping target categories first so clone is a clean copy of the scope.
    src_cats = [bc for bc in source.branch_categories.all() if keep_cat(bc.category_id)]
    cids = [bc.category_id for bc in src_cats]
    BranchItemPlacement.objects.filter(branch=target, category_id__in=cids).delete()
    BranchSubCategory.objects.filter(branch=target, sub_category__category_id__in=cids).delete()
    BranchCategory.objects.filter(branch=target, category_id__in=cids).delete()

    for bc in src_cats:
        BranchCategory.objects.create(branch=target, category_id=bc.category_id,
                                      display_order=bc.display_order)
    for bsc in source.branch_subcategories.select_related('sub_category'):
        if keep_cat(bsc.sub_category.category_id):
            BranchSubCategory.objects.create(branch=target, sub_category_id=bsc.sub_category_id,
                                             display_order=bsc.display_order)
    item_ids = set()
    for pl in source.placements.all():
        if keep_cat(pl.category_id):
            BranchItemPlacement.objects.create(
                branch=target, menu_item_id=pl.menu_item_id, category_id=pl.category_id,
                sub_category_id=pl.sub_category_id, display_order=pl.display_order)
            item_ids.add(pl.menu_item_id)
    for bmi in source.branch_items.filter(menu_item_id__in=item_ids):
        BranchMenuItem.objects.update_or_create(
            branch=target, menu_item_id=bmi.menu_item_id,
            defaults={'price_override': bmi.price_override})
    return JsonResponse({'ok': True})


@require_membership
@require_POST
def branch_item_price(request, slug, pk):
    branch = get_object_or_404(Branch, slug=slug)
    if not ensure_can_manage_branch(request, branch):
        return forbidden(request)
    item = get_object_or_404(MenuItem, pk=pk)
    bmi, _ = BranchMenuItem.objects.get_or_create(branch=branch, menu_item=item)
    price_str = request.POST.get('price', '').strip()
    if price_str:
        try:
            val = int(price_str)
        except ValueError:
            return JsonResponse({'error': 'Invalid price'}, status=400)
        if val <= 0:
            return JsonResponse({'error': 'Price must be a positive integer'}, status=400)
        bmi.price_override = val
    else:
        bmi.price_override = None
    bmi.save(update_fields=['price_override'])
    return JsonResponse({'price_override': bmi.price_override})
