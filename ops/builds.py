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
from django.urls import reverse
from django.views.decorators.http import require_POST

from menu import builds as build_service
from menu.models import (Branch, Company, MenuBuild, MenuBuildRow,
                         MenuBuildSection, MenuScan)
from menu.pipeline import category_icons
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
    """The build's front door: it sends you to whichever screen the build is
    actually on, so one link on a card is right at every stage.

    Closing the tab loses nothing — the state is in Postgres and the fragment
    below picks the run back up.
    """
    build = _build_or_404(build_id)
    if build.status == 'gate1':
        return redirect('ops:build_gate1', build_id=build.pk)
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


# ── Gate 1 ────────────────────────────────────────────────────────────────
# The one gate that stands between a fabricated price and a paying guest.
# With MENU_PRICE_VERIFY off the extractor never emits a null price — it
# invented one for all 27 it could not read — so no automatic rule can catch a
# wrong price. A human reading each section against the photograph is the
# control, which is why `prices_confirmed` is per section and is the only
# thing `build_advance` actually enforces.


def _section_or_404(build, section_id):
    return get_object_or_404(MenuBuildSection, pk=section_id, build=build)


def _row_or_404(build, row_id):
    return get_object_or_404(MenuBuildRow.objects.select_related('section'),
                             pk=row_id, build=build)


def _section_photo(section):
    """The document a section was read from, so the reviewer checks the rows
    against the card rather than against their memory of it."""
    row = section.rows.exclude(source_scan=None).select_related('source_scan').first()
    return row.source_scan if row else None


def _section_context(build, section):
    return {
        'build': build,
        'section': section,
        'rows': list(section.rows.all()),
        'photo': _section_photo(section),
        'sections': list(build.sections.all()),
        'icon_keys': _icon_keys(),
    }


def _render_section(request, build, section):
    """Every row mutation re-renders the whole section, not just the one card.

    A row can leave the section it was in (move), become two rows (split) or
    stop existing (delete), and a per-card swap cannot express any of those.
    One target that is always correct beats three that are usually correct.
    """
    return render(request, 'ops/builds/_section.html',
                  _section_context(build, section))


@platform_admin_required
def build_gate1(request, build_id):
    """One section at a time — the same layout at 1440 px and at 360 px.

    The gate is per section, so the screen shows one; the jump list is what
    lets a reviewer work out of order without turning it back into one long
    scroll where a section is confirmed without ever being looked at.
    """
    build = _build_or_404(build_id)
    sections = list(build.sections.all())
    if not sections:
        return render(request, 'ops/builds/gate1.html', {
            'active': 'builds', 'build': build, 'sections': [],
            'stats': _card_stats(build),
        })

    wanted = request.GET.get('section')
    current = next((s for s in sections if str(s.pk) == wanted), None)
    if current is None:
        # Land on the first section still needing a look, so the default path
        # through the screen is the work that is actually left.
        current = next((s for s in sections if not s.prices_confirmed), sections[0])

    index = sections.index(current)
    return render(request, 'ops/builds/gate1.html', {
        'active': 'builds', 'build': build, 'sections': sections,
        'section': current, 'rows': list(current.rows.all()),
        'photo': _section_photo(current),
        'previous': sections[index - 1] if index else None,
        'next': sections[index + 1] if index + 1 < len(sections) else None,
        'remaining': sum(1 for s in sections if not s.prices_confirmed),
        'stats': _card_stats(build),
        'icon_keys': _icon_keys(),
    })


def _icon_keys():
    """The icons a section may carry. Drawn from `category_icons` rather than
    listed here: every key there is guaranteed to have an SVG, and a key with
    no SVG renders as literal text on the guest menu."""
    return sorted({icon for _, icon in category_icons.RULES} | {category_icons.FALLBACK})


@platform_admin_required
@require_POST
def build_row_edit(request, build_id, row_id):
    """Correct what the card actually prints. The price is the field this whole
    gate exists for, so a blank one is stored as "no price" rather than 0 —
    Rs 0 is a real price a guest could be charged."""
    build = _build_or_404(build_id)
    row = _row_or_404(build, row_id)
    name = (request.POST.get('name') or '').strip()
    if name:
        row.name = name
    price = (request.POST.get('price') or '').strip()
    row.price = int(price) if price.isdigit() else None
    row.description = (request.POST.get('description') or row.description).strip()
    row.save(update_fields=['name', 'price', 'description'])
    return _render_section(request, build, row.section)


@platform_admin_required
@require_POST
def build_row_delete(request, build_id, row_id):
    build = _build_or_404(build_id)
    row = _row_or_404(build, row_id)
    section = row.section
    row.delete()
    return _render_section(request, build, section)


@platform_admin_required
@require_POST
def build_row_add(request, build_id, section_id):
    """A row the extractor missed. Added by hand, into the section being read —
    a printed line with no row is as wrong as a row with no printed line."""
    build = _build_or_404(build_id)
    section = _section_or_404(build, section_id)
    name = (request.POST.get('name') or '').strip()
    if name:
        price = (request.POST.get('price') or '').strip()
        last = section.rows.order_by('-display_order').first()
        MenuBuildRow.objects.create(
            build=build, section=section, name=name,
            price=int(price) if price.isdigit() else None,
            display_order=(last.display_order + 1) if last else 0)
    return _render_section(request, build, section)


@platform_admin_required
@require_POST
def build_row_split(request, build_id, row_id):
    """`Steam : Veg / Chicken / Buff — 150 / 250 / 250` is three products.

    ⚠ The variants do NOT inherit the parent's match or photograph. A printed
    variant label very often IS the protein (`Veg / Chicken / Buff` on one
    shared line is the commonest shape on these cards), and handing all three
    the bare parent's picture is exactly the religious/dietary violation the
    matcher's protein veto exists to prevent. They come out unmatched and are
    re-matched on their own names.
    """
    build = _build_or_404(build_id)
    row = _row_or_404(build, row_id)
    labels = [l.strip() for l in (request.POST.get('labels') or '').split(',') if l.strip()]
    prices = [p.strip() for p in (request.POST.get('prices') or '').split(',')]
    if len(labels) < 2:
        return _render_section(request, build, row.section)

    base = row.base_name or row.name
    for offset, label in enumerate(labels):
        price = prices[offset].strip() if offset < len(prices) else ''
        MenuBuildRow.objects.create(
            build=build, section=row.section,
            name=f'{base} ({label})', base_name=base, variant_label=label,
            price=int(price) if price.isdigit() else None,
            description=row.description, tags=list(row.tags or []),
            dietary_tags=list(row.dietary_tags or []),
            split_from=row.name, source_scan=row.source_scan,
            source_page=row.source_page,
            display_order=row.display_order + offset)
    section = row.section
    row.delete()
    return _render_section(request, build, section)


@platform_admin_required
@require_POST
def build_row_move(request, build_id, row_id):
    """`Apple` printed under JUICE is a different dish from `Apple` under MILK
    SHAKE, so which section a row sits in is menu data, not presentation."""
    build = _build_or_404(build_id)
    row = _row_or_404(build, row_id)
    target = _section_or_404(build, request.POST.get('section'))
    origin = row.section
    row.section = target
    row.save(update_fields=['section'])
    return _render_section(request, build, origin)


@platform_admin_required
@require_POST
def build_section_edit(request, build_id, section_id):
    """Rename and re-icon. A venue's sections stay in the venue's own words —
    this only fixes what the extractor misread.

    `prices_confirmed` is deliberately untouched: a rename is cosmetic, and
    silently clearing the tick would send a reviewer back through a section
    they had already checked against the photograph.
    """
    build = _build_or_404(build_id)
    section = _section_or_404(build, section_id)
    name = (request.POST.get('name') or '').strip()
    if name:
        section.name = name
    icon_key = (request.POST.get('icon_key') or '').strip()
    if icon_key:
        section.icon_key = icon_key
    section.save(update_fields=['name', 'icon_key'])
    return redirect(f"{_gate1_url(build)}?section={section.pk}")


def _gate1_url(build):
    return reverse('ops:build_gate1', args=[build.pk])


@platform_admin_required
@require_POST
def build_section_confirm(request, build_id, section_id):
    """"I have read these prices against the photograph." The single human act
    this gate is built around, and the only thing that opens it."""
    build = _build_or_404(build_id)
    section = _section_or_404(build, section_id)
    section.prices_confirmed = True
    section.save(update_fields=['prices_confirmed'])
    # Confirming moves you on: the next section still needing a look, or back
    # to the gate screen, which will then offer the exit.
    following = build.sections.filter(prices_confirmed=False).first()
    target = f"{_gate1_url(build)}?section={following.pk}" if following else _gate1_url(build)
    return redirect(target)


@platform_admin_required
@require_POST
def build_advance(request, build_id):
    """Gate 1's only exit. Refuses while any section is unconfirmed.

    The spec's original rule — block a row with no price — is kept below and is
    INERT: with MENU_PRICE_VERIFY off the extractor never emits a null price,
    so it can never fire on its own output. It stays for the day that guard
    ships, and it does catch a price a reviewer deliberately cleared. Do not
    mistake it for what is actually holding the gate.
    """
    build = _build_or_404(build_id)
    unconfirmed = list(build.sections.filter(prices_confirmed=False))
    if unconfirmed:
        return render(request, 'ops/builds/_gate_blocked.html',
                      {'build': build, 'unconfirmed': unconfirmed}, status=400)
    unpriced = list(build.rows.filter(price=None))     # inert today; see docstring
    if unpriced:
        return render(request, 'ops/builds/_gate_blocked.html',
                      {'build': build, 'unpriced': unpriced}, status=400)
    build.status = 'publishing'
    build.save(update_fields=['status'])
    return redirect('ops:build_detail', build_id=build.pk)
