import hashlib
import logging
import secrets
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.db.models import Count, Q
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from pgvector.django import CosineDistance

from core.models import Lead
from menu.dashboard.utils import generate_qr_for_branch
from menu.impersonation import make_token
from menu.models import Company, ImageAsset, Item, Membership, MenuScan
from menu.tasks import extract_menu_scan
from menu.pipeline import embed as image_embed
from menu.pipeline import embed as item_embed
from menu.pipeline import images as pipeline_images
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
    """Move a draft catalog item through the review lifecycle.

    Shared by the table review screen and (spec B) the card workbench.
    """
    item = get_object_or_404(Item, pk=item_id)
    action = request.POST.get('action')
    if action == 'approve':
        item.status = 'active'
        item.reviewed_by = request.user
        item.save(update_fields=['status', 'reviewed_by'])
        label = 'Approved ✓'
    elif action == 'reject':
        item.status = 'rejected'
        item.reviewed_by = request.user
        item.save(update_fields=['status', 'reviewed_by'])
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
    keeper.embedding = item_embed.embed(f"{keeper.name} {keeper.description}".strip())
    keeper.save(update_fields=['name', 'variant_label', 'embedding'])
    for sibling in siblings:
        sibling.status = 'merged'
        sibling.merged_into = keeper
        sibling.reviewed_by = request.user
        sibling.save(update_fields=['status', 'merged_into', 'reviewed_by'])
    _sync_scan_status(scan)
    return redirect('ops:scan_review', scan_id=scan.pk)


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
    with tempfile.TemporaryDirectory() as tmp:
        raw = str(Path(tmp) / 'raw')
        webp = str(Path(tmp) / 'out.webp')
        photo_search.download(source, url, raw)
        pipeline_images.to_thumbnail(raw, webp)
        data = Path(webp).read_bytes()
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
    ctx = {'a': asset, 'term': term, 'source': source, 'sources': photo_search.SOURCES}
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
