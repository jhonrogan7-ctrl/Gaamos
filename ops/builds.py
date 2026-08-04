"""The menu-build wizard's screens.

Separate from `ops/views.py` — that module is already 637 lines and serves the
pre-wizard scan workbench, which stays working untouched.

Every view here is apex-only and fail-closed. There is no tenant context on
these screens, so `Branch` is always reached through `all_objects` (or through
`MenuBuild.branch_list`), never through its default manager.
"""
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from menu import builds as build_service
from menu.models import (Branch, Company, MenuBuild, MenuBuildRow,
                         MenuBuildSection)
from menu.pipeline import xlsx_import
from menu.tasks import generate_row_image

from .permissions import platform_admin_required

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
    written down is a count that can disagree with the rows.

    The unit is the row, not the document: a build now starts from one
    spreadsheet and the work that takes time is one photograph per row.
    """
    rows = list(build.rows.all())
    with_image = sum(1 for r in rows if r.image_asset_id)
    return {
        'rows': len(rows),
        'sections': build.sections.count(),
        'with_image': with_image,
        'awaiting_image': sum(1 for r in rows
                              if r.image_state in ('none', 'generating')),
        'failed_image': sum(1 for r in rows if r.image_state == 'failed'),
        'needs_check': sum(1 for r in rows if r.notes),
        'branches': list(build.branch_list()),
        'percent': round(100 * with_image / len(rows)) if rows else 0,
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

    # A venue with no branch has nowhere to publish, and "pick at least one
    # branch" is a cruel thing to tell someone with nothing to pick.
    available = list(Branch.all_objects.filter(company=company))
    if not available:
        context['error'] = (f'{company.name} has no branch yet, so a menu has '
                            'nowhere to publish. Add one under Tenants first.')
        context['picked_company'] = company
        return render(request, 'ops/builds/new.html', context, status=200)

    branch_ids = request.POST.getlist('branches')
    # Scoped to the posted company on purpose: a branch id is guessable and this
    # form lists every tenant's branches. `len(...) != len(set(...))` catches an
    # id that belongs to somebody else rather than silently dropping it.
    branches = list(Branch.all_objects.filter(company=company, pk__in=branch_ids))
    if not branches or len(branches) != len(set(branch_ids)):
        names = ', '.join(b.name for b in available)
        context['error'] = (f'Tick at least one branch of {company.name} '
                            f'({names}) before starting.')
        context['picked_company'] = company
        return render(request, 'ops/builds/new.html', context, status=200)

    upload = request.FILES.get('sheet')
    if upload is None:
        context['error'] = ('Add the menu spreadsheet (.xlsx). Use the template '
                            'under Builds if you need one.')
        context['picked_company'] = company
        return render(request, 'ops/builds/new.html', context, status=200)

    parsed = xlsx_import.parse(upload)
    if not parsed.ok:
        # Nothing is created on a rejection. The sheet is machine-produced, so a
        # fault is usually the same fault on many rows: fix it once, upload once.
        context['errors'] = parsed.errors
        context['picked_company'] = company
        return render(request, 'ops/builds/new.html', context, status=200)

    build = MenuBuild.objects.create(company=company, created_by=request.user,
                                     status='generating')
    # `.set()` would raise: it diffs against `.all()`, which goes through
    # Branch's fail-closed TenantManager. `.add()` writes through the auto
    # -created through model instead, and the build is new so there is nothing
    # to clear.
    build.branches.add(*branches)
    build_service.rows_from_sheet(build, parsed.rows)
    build.sheet_name = parsed.sheet_name
    build.dashes_normalised = parsed.dashes
    build.save(update_fields=['sheet_name', 'dashes_normalised'])
    for row_id in build.rows.values_list('pk', flat=True):
        generate_row_image.delay(row_id)
    return redirect('ops:build_detail', build_id=build.pk)


@platform_admin_required
def build_detail(request, build_id):
    """The pictures, at every stage of the build.

    This used to bounce to review the moment the run finished, which stranded
    the rows: every row control — rename, reprice, move, delete, re-roll — lives
    on these tiles, and they became unreachable exactly when a reviewer wanted
    them. The review screen's own "back to the pictures" link bounced straight
    back here and out again.

    Reaching review is a button, not a redirect. Closing the tab loses nothing —
    the state is in Postgres and the fragment below picks the run back up.
    """
    build = _build_or_404(build_id)
    return render(request, 'ops/builds/generating.html', {
        'active': 'builds', 'build': build, 'stats': _card_stats(build),
        'sections': _sections_with_rows(build),
        # A flat list beside the (section, rows) pairs above: the move selector
        # on each tile needs sections, not pairs.
        'all_sections': list(build.sections.all()),
        # The full page and the polling fragment render the same partial, so
        # both must answer "is anything still moving?" the same way.
        'running': _still_generating(build),
    })


def _still_generating(build):
    """A row is finished when it has a picture or has given up trying. `failed`
    is finished — a picture that will never arrive must not strand the other
    109 rows in `generating` for ever."""
    return build.rows.filter(image_state__in=('none', 'generating')).exists()


def _sections_with_rows(build):
    """Sections in order, each with its rows. One query pair, not one per row —
    a 110-row card would otherwise be 110 queries per poll, every five seconds.
    """
    rows = list(build.rows.select_related('section').order_by('display_order'))
    sections = list(build.sections.order_by('display_order'))
    return [(s, [r for r in rows if r.section_id == s.pk]) for s in sections]


@platform_admin_required
def build_progress(request, build_id):
    """The HTMX polling target: the row grid, with each row's picture slot.

    Rows are rendered from the first poll, because they exist from the first
    second — 110 of them take 18+ minutes to photograph and nobody should watch
    a spinner for that. The images arrive underneath them.
    """
    build = _build_or_404(build_id)
    running = _still_generating(build)
    if not running and build.status == 'generating':
        build.status = 'review'
        build.save(update_fields=['status'])
    return render(request, 'ops/builds/_progress.html', {
        'build': build, 'running': running, 'stats': _card_stats(build),
        'sections': _sections_with_rows(build),
        'all_sections': list(build.sections.all()),
    })


def _section_or_404(build, section_id):
    return get_object_or_404(MenuBuildSection, pk=section_id, build=build)


def _row_or_404(build, row_id):
    return get_object_or_404(MenuBuildRow.objects.select_related('section'),
                             pk=row_id, build=build)


def _render_row(request, build, row):
    """Re-render ONE row card. A re-roll changes one picture, and swapping the
    whole section under the reviewer's cursor moves everything they were
    reading.

    A card is a fragment, so it is only a useful answer to HTMX. Without it the
    browser would navigate to a bare tile on a blank page — these controls carry
    a plain `action` so they work with JavaScript unavailable, and that promise
    is only kept if the no-HTMX path lands back on the build.
    """
    if not request.headers.get('HX-Request'):
        return redirect('ops:build_detail', build_id=build.pk)
    return render(request, 'ops/builds/_row_card.html',
                  {'build': build, 'row': row,
                   'all_sections': list(build.sections.all())})


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
    # The prompt is a field the operator edits like any other: a picture that is
    # wrong is usually a prompt that is wrong, and the fix belongs where the
    # mistake is visible.
    prompt = (request.POST.get('image_prompt') or '').strip()
    if prompt:
        row.image_prompt = prompt
    row.save(update_fields=['name', 'price', 'description', 'image_prompt'])
    return _render_row(request, build, row)


@platform_admin_required
def build_row_card(request, build_id, row_id):
    """One row card, for a card that is watching its own re-roll land.

    The grid's poll only runs during the build's `generating` phase. A re-roll
    happens after that, when nothing is polling any more, so without this the
    new picture would sit in the database until somebody reloaded the page by
    hand. The card polls itself instead of restarting the whole grid's poll:
    re-rolling one row out of 110 must not put the other 109 back on a timer.
    """
    build = _build_or_404(build_id)
    return _render_row(request, build, _row_or_404(build, row_id))


@platform_admin_required
@require_POST
def build_row_reroll(request, build_id, row_id):
    """Generate this row's picture again, with the prompt as it now reads.

    The same control serves two cases on purpose: a picture that failed and a
    picture that is simply wrong. A reviewer does not care which, and a second
    mechanism would only be a second thing to learn.
    """
    build = _build_or_404(build_id)
    row = _row_or_404(build, row_id)
    row.image_attempts += 1
    row.image_state = 'generating'
    row.image_error = ''
    row.save(update_fields=['image_attempts', 'image_state', 'image_error'])
    generate_row_image.delay(row.pk, attempt=row.image_attempts)
    return _render_row(request, build, row)


def _regrid(request, build):
    """Answer a mutation that changes the SHAPE of the grid, not one tile in it.

    A row can leave its section or stop existing, and neither is expressible as
    a per-card swap — the counts in the section headers move too. Telling HTMX
    to reload is one target that is always right, and these are rare, deliberate
    actions rather than something done while reading.
    """
    if not request.headers.get('HX-Request'):
        return redirect('ops:build_detail', build_id=build.pk)
    response = HttpResponse(status=204)
    response['HX-Refresh'] = 'true'
    return response


@platform_admin_required
@require_POST
def build_row_delete(request, build_id, row_id):
    """Deleting a row changes its section's count and can empty the section
    outright, so the answer is the page rather than the card."""
    build = _build_or_404(build_id)
    _row_or_404(build, row_id).delete()
    return _regrid(request, build)


@platform_admin_required
@require_POST
def build_row_move(request, build_id, row_id):
    """`Apple` printed under JUICE is a different dish from `Apple` under MILK
    SHAKE, so which section a row sits in is menu data, not presentation."""
    build = _build_or_404(build_id)
    row = _row_or_404(build, row_id)
    row.section = _section_or_404(build, request.POST.get('section'))
    row.save(update_fields=['section'])
    return _regrid(request, build)


def _publish_preview(build):
    """What a publish would write, counted from the rows themselves.

    Every number here is derived at read time. A stored count is a count that
    can quietly disagree with the rows it claims to describe, and this screen
    is the last thing a human reads before a tenant's live menu changes.
    """
    rows = list(build.rows.select_related('section'))
    sections = list(build.sections.all())
    return {
        'rows': len(rows),
        'sections': sections,
        'per_section': [(s, sum(1 for r in rows if r.section_id == s.pk))
                        for s in sections],
        'with_image': sum(1 for r in rows if r.image_asset_id),
        # Rs 0 is a real price a guest can be charged, and a row with no price
        # at all is a different problem. Counted apart so neither hides in the
        # other's total.
        'free': sum(1 for r in rows if r.price == 0),
        'unpriced': sum(1 for r in rows if r.price is None),
        'branches': list(build.branch_list()),
        # The one thing a reviewer is asked to look at. There is no gate any
        # more: the sheet is typed by the venue, so there is no fabricated
        # price to catch, and a note is advice rather than a blocker.
        'needs_check': [r for r in rows if r.notes],
    }


@platform_admin_required
def build_review(request, build_id):
    """The last screen before anything reaches a tenant. It says so plainly:
    up to this point every row has lived in scratch tables."""
    build = _build_or_404(build_id)
    return render(request, 'ops/builds/review.html', {
        'active': 'builds', 'build': build, 'preview': _publish_preview(build),
        'stats': _card_stats(build),
    })


@platform_admin_required
@require_POST
def build_publish(request, build_id):
    """Write the build into its tenant.

    Nothing blocks this any more. Gate 1 existed because a vision model invented
    a price for every price it could not read; a spreadsheet is typed by the
    venue, so there is no fabrication to catch. A row's `notes` still says "look
    at this one", but that is advice on the review screen, not a lock on the
    door — and while the check was still here, `prices_confirmed` defaulting to
    False made every spreadsheet build unpublishable.
    """
    build = _build_or_404(build_id)
    report = build_service.publish_build(build)
    return render(request, 'ops/builds/published.html', {
        'active': 'builds', 'build': build, 'report': report,
        'branches': list(build.branch_list()),
    })
