"""The menu-build wizard's service layer: rows, matching, publish.

No HTTP here. `ops/builds.py` renders; this module decides. Keeping them apart
is what lets the whole flow be tested without a request.
"""
from django.db import transaction

from menu import matching
from menu.models import MenuBuildRow, MenuBuildSection
from menu.pipeline import category_icons, normalize, prompts

DEFAULT_SECTION = 'Menu'


def section_for(build, name):
    """This build's section called `name`, created on first sight.

    The venue's own wording is kept verbatim -- `KAILASH TOUCH` stays
    `KAILASH TOUCH`. Only the icon is inferred.
    """
    clean = (name or '').strip() or DEFAULT_SECTION
    section = build.sections.filter(name=clean).first()
    if section is not None:
        return section
    return MenuBuildSection.objects.create(
        build=build, name=clean,
        display_order=build.sections.count(),
        icon_key=category_icons.for_section(clean))


@transaction.atomic
def rows_from_scan(build, scan):
    """Replace this scan's rows from its extraction. -> how many were written.

    Scoped to ONE scan on purpose: a five-page card is roughly nine minutes of
    model time, so a single unreadable photograph is re-uploaded alone and every
    other document's rows -- including corrections already typed into them --
    survive untouched.
    """
    payload = scan.raw_extraction or {}
    page_types = normalize.page_type_map(payload)
    MenuBuildRow.objects.filter(build=build, source_scan=scan).delete()

    written = 0
    for order, raw in enumerate(payload.get('items', [])):
        fields = normalize.normalize_item(raw, page_types)
        section = section_for(build, fields['raw_section'])
        MenuBuildRow.objects.create(
            build=build, section=section, display_order=order,
            name=fields['name'], base_name=fields['base_name'],
            variant_label=fields['variant_label'],
            description=fields['description'],
            # `normalize_item` names the price `reference_price` -- it maps onto
            # the catalog `Item` field set. On a build row it is the price this
            # venue printed, and nothing else.
            price=fields['reference_price'],
            tags=fields['tags'] or [],
            dietary_tags=fields['dietary_tags'] or [],
            raw_name=fields['raw_name'],
            raw_price_text=fields['raw_price_text'],
            split_from=fields['split_from'],
            confidence=fields['confidence'],
            source_scan=scan, source_page=fields['source_page'],
            # Composed now, not at gate 2: a re-roll must describe the dish the
            # card printed, and the row's name may have been edited by then.
            image_prompt=prompts.for_item(fields['name'], section.name))
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
