import hashlib
import logging
import secrets
from pathlib import Path

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.views.decorators.http import require_POST
from pgvector.django import CosineDistance

from core.models import Lead
from menu.dashboard.utils import generate_qr_for_branch
from menu.impersonation import make_token
from menu import publish
from menu.models import Branch, Company, ImageAsset, Item, Membership, MenuScan
from menu.tenancy import reset_current_company, set_current_company
from menu.tasks import extract_menu_scan, find_images_for_scan
from menu.pipeline import embed as image_embed
from menu.pipeline import item_embed
from menu.pipeline import intake as pipeline_intake
from menu.pipeline import normalize
from menu.pipeline import photo_search

from .forms import TenantCreateForm
from .permissions import platform_admin_required

logger = logging.getLogger(__name__)


def generate_password():
    return secrets.token_urlsafe(9)   # ~12 chars, URL-safe


def _stats():
    return {
        'new_leads': Lead.objects.filter(status='new').count(),
        'total_leads': Lead.objects.count(),
        'active_tenants': Company.objects.filter(status='active').count(),
        'suspended_tenants': Company.objects.filter(status='suspended').count(),
    }


@platform_admin_required
def index(request):
    """/platform/ → leads (the decorator bounces anonymous visitors to login)."""
    return redirect('ops:leads')


def login_view(request):
    if getattr(request, 'company', None) is not None:
        raise Http404
    error = ''
    if request.method == 'POST':
        user = authenticate(request,
                            username=request.POST.get('username', ''),
                            password=request.POST.get('password', ''))
        if user is not None and user.is_superuser:
            login(request, user)
            return redirect('ops:leads')
        # Same message for bad password and valid-but-not-superuser: no probing.
        error = 'Invalid credentials.'
    return render(request, 'ops/login.html', {'error': error})


@require_POST
def logout_view(request):
    logout(request)
    return redirect('ops:login')


@platform_admin_required
def leads(request):
    status = request.GET.get('status', '')
    qs = Lead.objects.select_related('company').order_by('-created_at')
    valid = {k for k, _ in Lead.STATUS_CHOICES}
    if status in valid:
        qs = qs.filter(status=status)
    return render(request, 'ops/leads.html', {
        'stats': _stats(), 'active': 'leads',
        'leads': qs, 'status_filter': status,
        'statuses': Lead.STATUS_CHOICES,
    })


@require_POST
@platform_admin_required
def lead_status(request, lead_id):
    lead = get_object_or_404(Lead, pk=lead_id)
    new_status = request.POST.get('status', '')
    if new_status not in {k for k, _ in Lead.STATUS_CHOICES}:
        return HttpResponseBadRequest('bad status')
    lead.status = new_status
    lead.save(update_fields=['status'])
    back = request.POST.get('next', '')
    # Same-site relative paths only (the form sends request.get_full_path).
    if not url_has_allowed_host_and_scheme(back, allowed_hosts=None):
        back = reverse('ops:leads')
    return redirect(back)


@platform_admin_required
def tenants(request):
    # Branch's default manager is tenant-scoped and fail-closed; from the apex
    # host there is no tenant context, so count via annotation, never c.branches.
    companies = (Company.objects.order_by('-created_at')
                 .annotate(branch_count=Count('branches')))
    password_note = request.session.pop('ops_password_note', None)
    return render(request, 'ops/tenants.html', {
        'stats': _stats(), 'active': 'tenants',
        'companies': companies, 'base_domain': settings.BASE_DOMAIN,
        'password_note': password_note,
    })


@require_POST
@platform_admin_required
def tenant_toggle(request, company_id):
    company = get_object_or_404(Company, pk=company_id)
    company.status = 'active' if company.status == 'suspended' else 'suspended'
    company.save(update_fields=['status'])
    return redirect('ops:tenants')


@require_POST
@platform_admin_required
def tenant_reset_password(request, company_id):
    company = get_object_or_404(Company, pk=company_id)
    owner_membership = (company.memberships
                        .filter(role=Membership.ROLE_OWNER)
                        .select_related('user').first())
    if owner_membership is None:
        return HttpResponseBadRequest('company has no owner')
    new_password = generate_password()
    owner_membership.user.set_password(new_password)
    owner_membership.user.save(update_fields=['password'])
    request.session['ops_password_note'] = {
        'company': company.name,
        'username': owner_membership.user.username,
        'password': new_password,
    }
    return redirect('ops:tenants')


@require_POST
@platform_admin_required
def tenant_impersonate(request, company_id):
    company = get_object_or_404(Company, pk=company_id, status='active')
    token = make_token(request.user, company)
    host = request.get_host()
    port = f":{host.split(':', 1)[1]}" if ':' in host else ''
    logger.info('impersonation issued: admin=%s(%s) company=%s',
                request.user.pk, request.user.username, company.slug)
    return redirect(
        f'{request.scheme}://{company.slug}.{settings.BASE_DOMAIN}{port}'
        f'/dashboard/impersonate/?token={token}')


@platform_admin_required
def tenant_new(request):
    lead = None
    lead_id = request.GET.get('lead', '')
    if lead_id.isdigit():
        lead = Lead.objects.filter(pk=lead_id).first()
    if request.method == 'POST':
        form = TenantCreateForm(request.POST)
        if form.is_valid():
            company, branch, user, password = form.save(lead=lead)
            base_url = f"{request.scheme}://{company.slug}.{settings.BASE_DOMAIN}"
            generate_qr_for_branch(branch, base_url)
            request.session['ops_created_note'] = {
                'company_id': company.id, 'username': user.username,
                'password': password,
            }
            return redirect('ops:tenant_created', company_id=company.id)
    else:
        initial = {}
        if lead is not None:
            initial = {'name': lead.venue_name, 'phone': lead.phone,
                       'email': lead.email}
        form = TenantCreateForm(initial=initial)
    return render(request, 'ops/tenant_form.html', {
        'stats': _stats(), 'active': 'new', 'form': form, 'lead': lead,
    })


@platform_admin_required
def tenant_created(request, company_id):
    company = get_object_or_404(Company, pk=company_id)
    note = request.session.pop('ops_created_note', None)
    if note and note.get('company_id') != company.id:
        note = None
    return render(request, 'ops/tenant_created.html', {
        'stats': _stats(), 'active': 'tenants', 'company': company,
        'base_domain': settings.BASE_DOMAIN, 'note': note,
    })


@platform_admin_required
def scans(request):
    if request.method == 'POST':
        upload = request.FILES.get('file')
        if not upload:
            return HttpResponseBadRequest('no file')
        scan = MenuScan.objects.create(
            source_cafe=request.POST.get('source_cafe', '').strip(),
            status='queued', created_by=request.user, file='')
        rel = f"scans/{scan.pk}_{upload.name}"
        dest = Path(settings.MEDIA_ROOT) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open('wb') as fh:
            for chunk in upload.chunks():
                fh.write(chunk)
        scan.file = rel
        scan.save(update_fields=['file'])
        extract_menu_scan.delay(scan.id)
        return redirect('ops:scans')
    return render(request, 'ops/scans.html',
                  {'scans': MenuScan.objects.all(), 'active': 'scans'})


@platform_admin_required
def scan_status(request, scan_id):
    scan = get_object_or_404(MenuScan, pk=scan_id)
    return render(request, 'ops/scans.html', {'scans': [scan], 'active': 'scans',
                                              'fragment': True})


def _dedup_matches(vec, limit=1):
    """Top catalog Items by cosine similarity to `vec`, above ITEM_MATCH_THRESHOLD.

    Takes a vector rather than text: every draft already carries the embedding
    the extraction task computed, so the review screen renders with zero API
    calls instead of one per row.
    """
    qs = (Item.objects.filter(status='active').exclude(embedding=None)
          .annotate(distance=CosineDistance('embedding', vec))
          .order_by('distance')[:limit])
    out = []
    for it in qs:
        sim = 1.0 - float(it.distance)
        if sim >= settings.ITEM_MATCH_THRESHOLD:
            out.append({'item': it, 'similarity': sim})
    return out


def _sync_scan_status(scan):
    """A scan is `reviewed` once no draft rows are left to decide on."""
    if scan is None:
        return
    if not Item.objects.filter(source_scan=scan, status='draft').exists():
        if scan.status != 'reviewed':
            scan.status = 'reviewed'
            scan.save(update_fields=['status'])


@platform_admin_required
def scan_review(request, scan_id):
    scan = get_object_or_404(MenuScan, pk=scan_id)
    drafts = Item.objects.filter(source_scan=scan, status='draft')
    has_catalog = Item.objects.filter(status='active').exclude(embedding=None).exists()
    grouped = {}
    for item in drafts:
        matches = (_dedup_matches(item.embedding)
                   if has_catalog and item.embedding is not None else [])
        grouped.setdefault(item.category, []).append(
            {'item': item, 'match': matches[0] if matches else None})
    return render(request, 'ops/scan_review.html', {
        'scan': scan, 'active': 'scans',
        'groups': [{'name': name, 'rows': rows} for name, rows in grouped.items()],
    })


@platform_admin_required
@require_POST
def item_action(request, item_id):
    """Move a scanned catalog item through the review lifecycle.

    Shared by the table review screen and (spec B) the card workbench. Rows that
    are already `active` are out of scope — a published catalog item tenants may
    be using is not review material, so it 404s rather than being flipped. Every
    other status stays actionable, so a misclicked reject or merge is recoverable.
    """
    item = get_object_or_404(Item.objects.exclude(status='active'), pk=item_id)
    action = request.POST.get('action')
    if action == 'approve':
        item.status = 'active'
        item.merged_into = None      # leaving a merge pointer behind would lie
        item.reviewed_by = request.user
        item.save(update_fields=['status', 'merged_into', 'reviewed_by'])
        label = 'Approved ✓'
    elif action == 'reject':
        item.status = 'rejected'
        item.merged_into = None
        item.reviewed_by = request.user
        item.save(update_fields=['status', 'merged_into', 'reviewed_by'])
        label = 'Rejected'
    elif action == 'merge':
        target = Item.objects.filter(pk=request.POST.get('merge_into'),
                                     status='active').first()
        if target is None:
            return HttpResponseBadRequest('merge_into must be an active item')
        item.status = 'merged'
        item.merged_into = target
        item.reviewed_by = request.user
        item.save(update_fields=['status', 'merged_into', 'reviewed_by'])
        label = f'Merged into #{target.pk}'
    else:
        return HttpResponseBadRequest('unknown action')
    _sync_scan_status(item.source_scan)
    return HttpResponse(f'<span class="ok">{label}</span>')


@platform_admin_required
@require_POST
def scan_combine(request, scan_id):
    """Fold over-split draft rows back into one.

    The extractor splits a multi-product line into an item per product (D5);
    when it splits too eagerly, staff pick a surviving row and the rest become
    `merged` into it. The keeper takes back the full printed line.
    """
    scan = get_object_or_404(MenuScan, pk=scan_id)
    keeper = Item.objects.filter(pk=request.POST.get('keep'), source_scan=scan,
                                 status='draft').first()
    if keeper is None:
        return HttpResponseBadRequest('keep must be a draft item of this scan')
    siblings = list(Item.objects.filter(pk__in=request.POST.getlist('sibling'),
                                        source_scan=scan, status='draft')
                    .exclude(pk=keeper.pk))
    if not siblings:
        return HttpResponseBadRequest('combine needs at least one other draft row')
    keeper.name = keeper.split_from or keeper.name
    keeper.variant_label = ''
    keeper.embedding = item_embed.embed_text(
        f"{keeper.name} {keeper.description}".strip())
    keeper.save(update_fields=['name', 'variant_label', 'embedding'])
    for sibling in siblings:
        sibling.status = 'merged'
        sibling.merged_into = keeper
        sibling.reviewed_by = request.user
        sibling.save(update_fields=['status', 'merged_into', 'reviewed_by'])
    _sync_scan_status(scan)
    return redirect('ops:scan_review', scan_id=scan.pk)


def _scan_image_source(raw):
    """Coerce a user-supplied source to a known one, defaulting to the setting."""
    return raw if raw in photo_search.SOURCES else settings.SCAN_IMAGE_SOURCE


@platform_admin_required
def item_find_photo(request, item_id):
    """Item-centric twin of image_find_another: search for a photo FOR A DISH.

    Stateless offset paging, exactly like the asset flow — the browser holds the
    position, the server holds nothing.
    """
    item = get_object_or_404(Item, pk=item_id)
    if request.GET.get('clear'):
        return HttpResponse('')
    try:
        offset = int(request.GET.get('offset', 0))
    except (TypeError, ValueError):
        offset = 0
    term = (request.GET.get('term') or item.name or item.raw_name or '').strip()
    source = _scan_image_source(request.GET.get('source'))
    ctx = {'term': term, 'source': source, 'sources': photo_search.SOURCES,
           'find_url': reverse('ops:item_find_photo', args=[item.pk]),
           'use_url': reverse('ops:item_use_photo', args=[item.pk]),
           'slot': f'item-{item.pk}', 'card_id': f'sc-card-{item.pk}'}
    try:
        results = photo_search.search(source, term, limit=20)
    except Exception:
        ctx['error'] = True
        return render(request, 'ops/_image_preview.html', ctx)
    current = item.image_asset.origin_url if item.image_asset_id else ''
    candidates = [c for c in results
                  if not current or (c.get('page') != current and c.get('url') != current)]
    if offset < 0 or offset >= len(candidates):
        ctx['no_more'] = True
        return render(request, 'ops/_image_preview.html', ctx)
    ctx['cand'] = candidates[offset]
    ctx['next_offset'] = offset + 1
    return render(request, 'ops/_image_preview.html', ctx)


@platform_admin_required
@require_POST
def item_use_photo(request, item_id):
    """Download the chosen candidate, deposit it in the library, attach it.

    The asset is recorded with the item's tags, so the library is searchable from
    the first deposit rather than after a human gets round to captioning it.
    """
    item = get_object_or_404(Item, pk=item_id)
    url = request.POST.get('url', '').strip()
    if not url:
        return HttpResponseBadRequest('missing url')
    page = request.POST.get('page', '').strip()
    source = _scan_image_source(request.POST.get('source'))
    webp = photo_search.fetch_thumbnail(source, url)
    asset = pipeline_intake.record(
        source=source, webp_bytes=webp, item_name=item.name,
        found_for_slug=slugify(item.name), origin_url=page or url, tags=item.tags)
    if asset is None:
        return HttpResponseBadRequest('that photo was rejected before')
    item.image_asset = asset
    item.save(update_fields=['image_asset'])
    return render(request, 'ops/_scan_item_card.html', {'it': item})


@platform_admin_required
@require_POST
def item_edit_tags(request, item_id):
    """Save hand-corrected tags through spec A's validator.

    D6 is enforced here as well as at extraction: a tag whose words are not in
    the item's own printed name is dropped, whoever typed it. No re-embed —
    `Item.embedding` derives from name + description, untouched by this view.
    """
    item = get_object_or_404(Item, pk=item_id)
    raw = [t.strip() for t in request.POST.get('tags', '').split(',') if t.strip()]
    item.tags = normalize.clean_tags(raw, item.raw_name or item.name)
    item.save(update_fields=['tags'])
    return render(request, 'ops/_scan_item_card.html', {'it': item})


def _workbench_items(scan):
    """The rows a human is still working on: rejected and merged are decided."""
    return (Item.objects.filter(source_scan=scan)
            .exclude(status__in=('rejected', 'merged')))


def _image_progress(scan):
    items = _workbench_items(scan)
    total = items.count()
    return {'scan': scan, 'total': total,
            'with_photo': items.filter(image_asset__isnull=False).count()}


@platform_admin_required
def scan_workbench(request, scan_id):
    """Card grid over this scan's rows — the image half of the review job.

    Data corrections live on the table view (B2); both screens act on the same
    rows, so neither owns state the other lacks.
    """
    scan = get_object_or_404(MenuScan, pk=scan_id)
    ctx = _image_progress(scan)
    ctx.update({'active': 'scans', 'items': _workbench_items(scan)})
    return render(request, 'ops/scan_workbench.html', ctx)


@platform_admin_required
def scan_image_progress(request, scan_id):
    scan = get_object_or_404(MenuScan, pk=scan_id)
    return render(request, 'ops/_scan_image_progress.html', _image_progress(scan))


@platform_admin_required
@require_POST
def scan_find_images(request, scan_id):
    scan = get_object_or_404(MenuScan, pk=scan_id)
    result = find_images_for_scan.delay(scan.pk)
    scan.image_task_id = getattr(result, 'id', '') or ''
    scan.save(update_fields=['image_task_id'])
    return redirect('ops:scan_workbench', scan_id=scan.pk)


@platform_admin_required
def scan_publish(request, scan_id):
    """Publish this scan's approved rows into one tenant (B4).

    Scoped to the scanned menu in hand, matching the scan → review → hand to the
    client flow. Composing a menu from the whole catalog is a different screen
    for a different job.
    """
    scan = get_object_or_404(MenuScan, pk=scan_id)
    active = Item.objects.filter(source_scan=scan, status='active')
    if request.method != 'POST':
        # This is an apex screen, so there is NO tenant context: never walk a
        # scoped related manager like `company.branches` (see the comment above
        # `tenants`). Branches are fetched explicitly via all_objects instead.
        return render(request, 'ops/scan_publish.html', {
            'scan': scan, 'active': 'scans', 'items': active,
            'companies': Company.objects.filter(status='active').order_by('name'),
            'branches': (Branch.all_objects.select_related('company')
                         .order_by('company__name', 'name')),
        })

    company = Company.objects.filter(pk=request.POST.get('company')).first()
    if company is None:
        return HttpResponseBadRequest('pick a company')
    branch_ids = request.POST.getlist('branch')
    branches = list(Branch.all_objects.filter(company=company, pk__in=branch_ids))
    if not branches or len(branches) != len(set(branch_ids)):
        return HttpResponseBadRequest('pick at least one branch of that company')
    items = list(active.filter(pk__in=request.POST.getlist('item')))

    token = set_current_company(company)
    try:
        with transaction.atomic():
            report = publish.publish_items(company, branches, items)
            scan.status = 'imported'
            scan.save(update_fields=['status'])
    finally:
        reset_current_company(token)
    return render(request, 'ops/_publish_report.html', {
        'scan': scan, 'active': 'scans', 'company': company, 'report': report,
    })


@platform_admin_required
def image_review(request):
    """Staff review queue: every pending library asset awaiting verification."""
    assets = ImageAsset.objects.filter(status='pending').order_by('-created_at')
    return render(request, 'ops/images_review.html', {
        'stats': _stats(), 'active': 'images', 'assets': assets,
    })


@platform_admin_required
@require_POST
def image_action(request, asset_id):
    asset = get_object_or_404(ImageAsset, pk=asset_id)
    action = request.POST.get('action')
    if action == 'approve':
        asset.status = 'verified'
    elif action == 'reject':
        asset.status = 'rejected'
    else:
        return HttpResponseBadRequest('unknown action')
    asset.reviewed_at = timezone.now()
    asset.reviewed_by = request.user
    asset.save(update_fields=['status', 'reviewed_at', 'reviewed_by'])
    return redirect('ops:images')


@platform_admin_required
@require_POST
def image_edit(request, asset_id):
    asset = get_object_or_404(ImageAsset, pk=asset_id)
    caption = request.POST.get('caption', '').strip()
    tags = [t.strip() for t in request.POST.get('tags', '').split(',') if t.strip()]
    asset.tags = tags
    asset.save(update_fields=['tags'])
    if caption != asset.caption:
        asset.caption = caption
        asset.embedding = image_embed.embed(caption)
        asset.save(update_fields=['caption', 'embedding'])
    return redirect('ops:images')


@platform_admin_required
def image_browse(request):
    """Browse/filter the verified pool by free text (caption/name) or a tag."""
    q = request.GET.get('q', '').strip()
    tag = request.GET.get('tag', '').strip()
    assets = ImageAsset.objects.filter(status='verified').order_by('-reviewed_at')
    if q:
        assets = assets.filter(Q(caption__icontains=q) | Q(name__icontains=q))
    if tag:
        assets = assets.filter(tags__contains=[tag])
    return render(request, 'ops/images_browse.html', {
        'stats': _stats(), 'active': 'images',
        'assets': assets, 'q': q, 'tag': tag,
    })


@platform_admin_required
@require_POST
def image_use_photo(request, asset_id):
    asset = get_object_or_404(ImageAsset, pk=asset_id)
    url = request.POST.get('url', '').strip()
    if not url:
        return HttpResponseBadRequest('missing url')
    page = request.POST.get('page', '').strip()
    source = request.POST.get('source') or 'pexels'
    if source not in photo_search.SOURCES:
        source = 'pexels'
    data = photo_search.fetch_thumbnail(source, url)
    content_hash = hashlib.sha256(data).hexdigest()
    rel = f'imagelib/{content_hash}.webp'
    dest = Path(settings.MEDIA_ROOT) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    page_val = page or url
    hash_clash = (ImageAsset.objects.filter(content_hash=content_hash)
                  .exclude(pk=asset.pk).exists())
    url_clash = (ImageAsset.objects.filter(origin_url=page_val)
                 .exclude(pk=asset.pk).exists())
    asset.file = rel
    asset.source = source
    asset.content_hash = '' if hash_clash else content_hash
    asset.origin_url = '' if url_clash else page_val
    asset.save(update_fields=['file', 'origin_url', 'source', 'content_hash'])
    return render(request, 'ops/_image_card.html', {'a': asset, 'review': True})


@platform_admin_required
def image_find_another(request, asset_id):
    asset = get_object_or_404(ImageAsset, pk=asset_id)
    if request.GET.get('clear'):
        return HttpResponse('')
    try:
        offset = int(request.GET.get('offset', 0))
    except (TypeError, ValueError):
        offset = 0
    term = (request.GET.get('term') or asset.caption or asset.found_for_slug or '').strip()
    source = request.GET.get('source') or 'pexels'
    if source not in photo_search.SOURCES:
        source = 'pexels'
    ctx = {'a': asset, 'term': term, 'source': source, 'sources': photo_search.SOURCES,
           'find_url': reverse('ops:image_find_another', args=[asset.pk]),
           'use_url': reverse('ops:image_use_photo', args=[asset.pk]),
           'slot': asset.pk, 'card_id': f'il-card-{asset.pk}'}
    try:
        results = photo_search.search(source, term, limit=20)
    except Exception:
        ctx['error'] = True
        return render(request, 'ops/_image_preview.html', ctx)
    candidates = [c for c in results
                  if c.get('page') != asset.origin_url and c.get('url') != asset.origin_url]
    if offset < 0 or offset >= len(candidates):
        ctx['no_more'] = True
        return render(request, 'ops/_image_preview.html', ctx)
    ctx['cand'] = candidates[offset]
    ctx['next_offset'] = offset + 1
    return render(request, 'ops/_image_preview.html', ctx)
