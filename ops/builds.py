"""The menu-build wizard's screens.

Separate from `ops/views.py` — that module is already 637 lines and serves the
pre-wizard scan workbench, which stays working untouched.

Every view here is apex-only and fail-closed. There is no tenant context on
these screens, so `Branch` is always reached through `all_objects` (or through
`MenuBuild.branch_list`), never through its default manager.
"""
from pathlib import Path

from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from menu import builds as build_service
from menu.models import Branch, Company, MenuBuild, MenuScan
from menu.tasks import extract_menu_scan

from .permissions import platform_admin_required

# Statuses whose documents are still moving. Used to decide whether the
# progress fragment keeps polling.
RUNNING_SCAN_STATUSES = ('queued', 'processing')


def _build_or_404(build_id):
    return get_object_or_404(
        MenuBuild.objects.select_related('company'), pk=build_id)


def _venue_picker():
    """Companies and their branches for the new-build form.

    Branches come from `all_objects` and carry their company: this is an apex
    screen listing every tenant, which is exactly why `build_new` re-checks
    that a posted branch belongs to the posted company.
    """
    return {
        'companies': Company.objects.filter(status='active').order_by('name'),
        'branches': (Branch.all_objects.select_related('company')
                     .order_by('company__name', 'name')),
    }


def _card_stats(build):
    """The numbers on a build card. Derived, never stored — a count that is
    written down is a count that can disagree with the rows."""
    sections = build.sections.all()
    confirmed = sum(1 for s in sections if s.prices_confirmed)
    scans = list(build.scans.all())
    return {
        'rows': build.rows.count(),
        'sections': len(sections),
        'sections_confirmed': confirmed,
        'with_image': build.rows.exclude(image_asset=None).count(),
        'documents': len(scans),
        'documents_done': sum(1 for s in scans if s.status in ('extracted', 'reviewed',
                                                               'imported')),
        'documents_failed': sum(1 for s in scans if s.status == 'failed'),
        'branches': list(build.branch_list()),
        'percent': round(100 * confirmed / len(sections)) if sections else 0,
    }


@platform_admin_required
def builds_list(request):
    """Every build, newest first. Cards, never a table (founder rule)."""
    rows = [{'build': b, 'stats': _card_stats(b)}
            for b in MenuBuild.objects.select_related('company')]
    return render(request, 'ops/builds/list.html', {
        'active': 'builds', 'builds': rows,
    })


@platform_admin_required
def build_new(request):
    """Pick the venue and branches, drop the card in, start extraction.

    A build knows where it publishes before a single model call is spent, so
    an extraction can never finish with nowhere to go.
    """
    context = {'active': 'builds', **_venue_picker()}
    if request.method != 'POST':
        return render(request, 'ops/builds/new.html', context)

    company = Company.objects.filter(pk=request.POST.get('company')).first()
    if company is None:
        context['error'] = 'Pick a venue.'
        return render(request, 'ops/builds/new.html', context, status=200)

    branch_ids = request.POST.getlist('branches')
    # Scoped to the posted company on purpose: a branch id is guessable and this
    # form lists every tenant's branches. `len(...) != len(set(...))` catches an
    # id that belongs to somebody else rather than silently dropping it.
    branches = list(Branch.all_objects.filter(company=company, pk__in=branch_ids))
    if not branches or len(branches) != len(set(branch_ids)):
        context['error'] = 'Pick at least one branch of that venue.'
        context['picked_company'] = company
        return render(request, 'ops/builds/new.html', context, status=200)

    uploads = request.FILES.getlist('documents')
    if not uploads:
        context['error'] = 'Add at least one photograph or PDF of the printed card.'
        context['picked_company'] = company
        return render(request, 'ops/builds/new.html', context, status=200)

    build = MenuBuild.objects.create(company=company, created_by=request.user,
                                     status='extracting')
    # `.set()` would raise: it diffs against `.all()`, which goes through
    # Branch's fail-closed TenantManager. `.add()` writes through the auto
    # -created through model instead, and the build is new so there is nothing
    # to clear. See `MenuBuild.branch_list` for the read side.
    build.branches.add(*branches)
    for upload in uploads:
        _store_document(build, upload)
    return redirect('ops:build_detail', build_id=build.pk)


def _store_document(build, upload):
    """Save one uploaded document and queue its own extraction job.

    One job per document, not per build: a five-page card is roughly nine
    minutes of model time, and a single unreadable photograph must be
    re-takeable on its own without re-reading the other four.
    """
    scan = MenuScan.objects.create(status='queued', file='', build=build,
                                   source_cafe=build.company.name)
    rel = f'scans/{scan.pk}_{upload.name}'
    dest = Path(settings.MEDIA_ROOT) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open('wb') as fh:
        for chunk in upload.chunks():
            fh.write(chunk)
    scan.file = rel
    scan.save(update_fields=['file'])
    extract_menu_scan.delay(scan.id)
    return scan


@platform_admin_required
def build_detail(request, build_id):
    """The extraction screen. Closing the tab loses nothing — the state is in
    Postgres and the fragment below picks the run back up."""
    build = _build_or_404(build_id)
    scans = list(build.scans.all())
    return render(request, 'ops/builds/extracting.html', {
        'active': 'builds', 'build': build, 'stats': _card_stats(build),
        'scans': scans,
        # The full page and the polling fragment render the same partial, so
        # both must answer "is anything still moving?" the same way.
        'running': any(s.status in RUNNING_SCAN_STATUSES for s in scans),
    })


@platform_admin_required
def build_progress(request, build_id):
    """The HTMX polling target: one card per document, with its error if it has
    one, and a re-upload control for a document that failed."""
    build = _build_or_404(build_id)
    scans = list(build.scans.all())
    running = any(s.status in RUNNING_SCAN_STATUSES for s in scans)
    if not running and build.status == 'extracting' and scans:
        _finish_extraction(build, scans)
    return render(request, 'ops/builds/_progress.html', {
        'build': build, 'scans': scans, 'running': running,
        'stats': _card_stats(build),
    })


def _finish_extraction(build, scans):
    """Turn every extracted document into rows, then match once.

    Matching runs over the whole build rather than per document: `Apple` under
    JUICE is a different dish from `Apple` under MILK SHAKE, and sections only
    exist once every document has landed.
    """
    for scan in scans:
        if scan.status in ('extracted', 'reviewed', 'imported'):
            build_service.rows_from_scan(build, scan)
    build_service.match_build_rows(build)
    build.status = 'gate1'
    build.save(update_fields=['status'])


@platform_admin_required
@require_POST
def build_rescan(request, build_id, scan_id):
    """Re-take one page. Replaces that document's file and re-queues only it —
    every other document's rows, and any correction typed into them, survive.
    """
    build = _build_or_404(build_id)
    scan = get_object_or_404(MenuScan, pk=scan_id, build=build)
    upload = request.FILES.get('document')
    if upload is None:
        return redirect('ops:build_detail', build_id=build.pk)
    rel = f'scans/{scan.pk}_{upload.name}'
    dest = Path(settings.MEDIA_ROOT) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open('wb') as fh:
        for chunk in upload.chunks():
            fh.write(chunk)
    scan.file, scan.status, scan.error = rel, 'queued', ''
    scan.save(update_fields=['file', 'status', 'error'])
    build.status = 'extracting'
    build.save(update_fields=['status'])
    extract_menu_scan.delay(scan.id)
    return redirect('ops:build_detail', build_id=build.pk)
