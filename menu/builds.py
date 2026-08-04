"""The menu-build wizard's service layer: rows, matching, publish.

No HTTP here. `ops/builds.py` renders; this module decides. Keeping them apart
is what lets the whole flow be tested without a request.
"""
from django.db import transaction

from menu import matching
from menu import publish as publish_mod
from menu.models import Item, MenuBuildRow, MenuBuildSection
from menu.pipeline import category_icons, name_norm, normalize, prompts

DEFAULT_SECTION = 'Menu'


def section_for(build, name, sub_name=''):
    """This build's section for a (category, subcategory) pair, made on sight.

    The venue's own wording is kept verbatim -- `KAILASH TOUCH` stays
    `KAILASH TOUCH`. Only the icon is inferred, and it is inferred from the
    category: a subcategory called `Momo` under `Nepali Foods` should not get a
    different icon from `Noodles` beside it.
    """
    clean = (name or '').strip() or DEFAULT_SECTION
    sub = (sub_name or '').strip()
    section = build.sections.filter(name=clean, sub_name=sub).first()
    if section is not None:
        return section
    return MenuBuildSection.objects.create(
        build=build, name=clean, sub_name=sub,
        display_order=build.sections.count(),
        icon_key=category_icons.for_section(clean))


@transaction.atomic
def rows_from_sheet(build, sheet_rows):
    """Replace this build's rows from a parsed spreadsheet. -> how many.

    Whole-build, not per document: a spreadsheet arrives complete, so there is
    no equivalent of re-taking one unreadable photograph. Re-uploading a
    corrected sheet replaces everything, which is the behaviour a person
    expects from a file they just fixed.

    The prompt is composed HERE rather than at generation time, so the operator
    can read and edit it before a single image is spent -- and so a re-roll
    describes the dish the sheet named even if the row's name was edited since.
    """
    MenuBuildRow.objects.filter(build=build).delete()
    build.sections.all().delete()

    written = 0
    for order, sheet_row in enumerate(sheet_rows):
        section = section_for(build, sheet_row.category, sheet_row.sub_category)
        MenuBuildRow.objects.create(
            build=build, section=section, display_order=order,
            name=sheet_row.item, base_name=sheet_row.item,
            variant_label=sheet_row.variant,
            description=sheet_row.description,
            price=sheet_row.price,
            notes=sheet_row.notes,
            # `for_item` takes the subject and appends the shared style block.
            # Passing the subject is the whole reason the sheet carries one:
            # with no subject the printed name would have to serve as its own
            # description, which is what the photographed path had to do.
            image_prompt=prompts.for_item(sheet_row.item, section.name,
                                          subject=sheet_row.subject))
        written += 1
    return written


def match_build_rows(build, *, embedder=matching._UNSET):
    """Match every row against the library. -> {'auto': n, 'suggested': n, 'none': n}.

    ⚠ Only an `auto` (exact) match takes an image. A fuzzy match may suggest but
    never auto-apply (founder, 2026-08-02): the vector layer was measured
    handing a gin row a Fanta photograph at cosine 0.71, and gate 2 -- the click
    that would catch it -- does not exist until 4b. The candidate is still
    recorded, so 4b can offer it without re-running the matcher.
    """
    rows = list(build.rows.select_related('section'))
    if not rows:
        return {'auto': 0, 'suggested': 0, 'none': 0}

    payload = [matching.Row(name=r.name, section=r.section.name,
                            dietary_tags=tuple(r.dietary_tags or []))
               for r in rows]
    matches = matching.match_rows(payload, company=build.company, embedder=embedder)

    counts = {'auto': 0, 'suggested': 0, 'none': 0}
    for row, match in zip(rows, matches):
        counts[match.decision] = counts.get(match.decision, 0) + 1
        row.match_state = match.decision
        row.match_score = match.score
        row.match_method = match.layer
        row.matched_item_id = match.entry_id
        fields = ['match_state', 'match_score', 'match_method', 'matched_item']
        if match.decision == 'auto' and match.entry_id is not None:
            entry = row.matched_item
            if entry.image_asset_id:
                row.image_asset_id = entry.image_asset_id
                row.image_state = 'matched'
                fields += ['image_asset', 'image_state']
        row.save(update_fields=fields)
    return counts


@transaction.atomic
def publish_build(build):
    """Write this build's rows into its tenant, and grow the library.

    One transaction: the tenant menu and the library move together or not at
    all. Re-publishing is idempotent on both sides -- deterministic slugs update
    the same `MenuItem`, and a row that already contributed does not inflate
    `use_count` a second time.
    """
    rows = list(build.rows.select_related('section'))
    branches = list(build.branch_list())

    report = publish_mod.publish_rows(build.company, branches, [
        publish_mod.PublishRow(
            name=r.name, price=r.price, description=r.description,
            dietary_tags=list(r.dietary_tags or []),
            category=r.section.name, category_icon=r.section.icon_key,
            sub_category=r.section.sub_name,
            image_asset=r.image_asset if r.image_asset_id else None)
        for r in rows])

    report.library_created = 0
    report.library_reused = 0
    # Read BEFORE any linking: once `_link_published_item` runs, every row looks
    # like it has always contributed, and `use_count` could never tell a first
    # publish from a fifth.
    contributed_before = {r.pk: r.published_item_id is not None for r in rows}
    for row in rows:
        _link_published_item(row, build)
        if row.matched_item_id:
            _bump_usage(row, build, report, first_time=not contributed_before[row.pk])
        else:
            _grow_library(row, build, report,
                          first_time=not contributed_before[row.pk])

    build.status = 'published'
    build.save(update_fields=['status'])
    return report


def _link_published_item(row, build):
    from menu.models import MenuItem
    slug = publish_mod.unique_item_slug(build.company, row.name)
    item = MenuItem.all_objects.filter(company=build.company, slug=slug).first()
    if item is not None and row.published_item_id != item.pk:
        row.published_item = item
        row.save(update_fields=['published_item'])


def _bump_usage(row, build, report, *, first_time):
    """A venue that serves an entry counts once, however often it re-publishes.

    Incremented, not recomputed from the entry's build rows. Recomputing looks
    tidier and is wrong: an entry's existing `use_count` may have come from
    phase 1's library backfill, whose venues never went through a build, and a
    recompute would silently erase every one of them.

    Two conditions keep it honest. `first_time` is read before this publish
    linked anything, so re-publishing the same build cannot inflate the count;
    and a company that already has a published row against this entry does not
    count twice, so a card printing the same dish in two sections still counts
    as one venue.
    """
    entry = row.matched_item
    counted = (entry.build_rows.exclude(published_item=None)
               .filter(build__company=build.company)
               .exclude(pk=row.pk).exists())
    if first_time and not counted:
        entry.use_count = entry.use_count + 1
        entry.save(update_fields=['use_count'])
    report.library_reused += 1


def _grow_library(row, build, report, *, first_time):
    """An unmatched row teaches the platform a name it did not know.

    Imageless in 4a -- there is no gate where a human accepts an image yet --
    but the next venue printing this dish matches the NAME, which is most of
    the value.
    """
    search_name, variant = name_norm.entry_key(row.name, row.section.name)
    existing = next((e for e in Item.objects.filter(status='active',
                                                    search_name=search_name)
                     if name_norm.normalize(e.variant_label) == variant), None)
    if existing is not None:
        row.matched_item = existing
        row.save(update_fields=['matched_item'])
        _bump_usage(row, build, report, first_time=first_time)
        return
    entry = Item.objects.create(
        name=row.name, base_name=row.base_name, variant_label=row.variant_label,
        search_name=search_name, description=row.description,
        category=row.section.name, dietary_tags=list(row.dietary_tags or []),
        reference_price=row.price, currency='NPR',
        image_prompt=row.image_prompt, origin_company=build.company,
        status='active', use_count=1)
    row.matched_item = entry
    row.save(update_fields=['matched_item'])
    report.library_created += 1
