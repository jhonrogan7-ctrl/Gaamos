"""Publishing a catalog `Item` into a tenant's live menu.

Shared by the `import_menu` fixture command and the scan workbench (B9), so
there is one implementation of "upsert a MenuItem, link it to the branches, copy
its image in" rather than two that drift.

Nothing here creates a company or a branch: publishing is additive and
idempotent, and callers pass an existing tenant.
"""
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings
from django.utils.text import slugify

from menu.imaging import compute_focal_point
from menu.models import (BranchCategory, BranchItemPlacement, BranchMenuItem,
                         Category, MenuItem)


@dataclass
class PublishReport:
    created: int = 0
    updated: int = 0
    zero_priced: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    categories_created: list = field(default_factory=list)


def unique_item_slug(company, name, *, taken=None):
    """A stable per-company slug for `name`.

    Deterministic on purpose: re-publishing a corrected scan must land on the
    same `MenuItem` row rather than growing a duplicate menu. Two genuinely
    different names that slugify alike get -2, -3 … in first-published order.
    """
    base = slugify(name) or slugify(name, allow_unicode=True) or 'item'
    base = base[:80]
    taken = set(taken or ())
    existing = {mi.slug: mi.name for mi in
                MenuItem.all_objects.filter(company=company, slug__startswith=base)}
    if existing.get(base, name) == name and base not in taken:
        return base
    n = 2
    while True:
        candidate = f"{base[:76]}-{n}"
        if existing.get(candidate, name) == name and candidate not in taken:
            return candidate
        n += 1


def ensure_category(company, branches, *, name, slug=None, display_order=0,
                    icon_key='', hours_note='', update=False):
    """get_or_create one tenant category and link it to every branch.

    `update=True` makes the caller's values authoritative on an existing row.
    That is right for `import_menu`, whose fixture IS the source of truth, and
    wrong for a scan re-publish: under B5 renaming and reordering is the
    dashboard's job, so publishing twice must not undo a venue's own edit.
    """
    fields = {'name': name, 'display_order': display_order,
              'icon_key': icon_key, 'hours_note': hours_note}
    upsert = (Category.all_objects.update_or_create if update
              else Category.all_objects.get_or_create)
    cat, created = upsert(company=company, slug=slug or slugify(name)[:50],
                          defaults=fields)
    for b in branches:
        BranchCategory.objects.get_or_create(
            branch=b, category=cat, defaults={'display_order': display_order})
    return cat, created


def ensure_categories(company, branches, names):
    """-> ({name: Category}, [names created]), display_order by first appearance.

    The venue's own section names are their brand (B5): `KAILASH TOUCH` stays
    `KAILASH TOUCH`. Renaming and reordering is the dashboard's job.
    """
    out, created = {}, []
    for name in names:
        label = (name or '').strip() or 'Menu'
        if label in out:
            continue
        cat, was_created = ensure_category(company, branches, name=label,
                                           display_order=len(out))
        out[label] = cat
        if was_created:
            created.append(label)
    return out, created


def copy_image_to_tenant(company, item_slug, src_path):
    """Copy an image into tenant media -> (image_url, focal_x, focal_y).

    Tenant media is copied, not referenced (B10): it keeps `items/<company>/…`
    isolated for the R2 move and satisfies the rule that a tenant-derived
    filename carries the company.
    """
    rel = f"items/{company.slug}/{item_slug}.webp"
    dest = Path(settings.MEDIA_ROOT) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(src_path), dest)
    focal_x, focal_y = compute_focal_point(str(dest))
    return f"{settings.MEDIA_URL}{rel}", focal_x, focal_y


def upsert_menu_item(company, branches, *, slug, name, description, price,
                     dietary_tags, category, sub_category=None, display_order=0,
                     popular=False, featured=False):
    """Upsert on (company, slug) and link the item into every branch."""
    item, created = MenuItem.all_objects.update_or_create(
        company=company, slug=slug,
        defaults={'name': name, 'description': description, 'price': price,
                  'dietary_tags': list(dietary_tags or []),
                  'is_popular': popular, 'is_featured': featured})
    for b in branches:
        BranchMenuItem.objects.get_or_create(branch=b, menu_item=item)
        if category is not None:
            BranchItemPlacement.objects.get_or_create(
                branch=b, menu_item=item, category=category, sub_category=sub_category,
                defaults={'display_order': display_order})
    return item, created


def publish_items(company, branches, items):
    """Publish catalog Items into `company`'s menu on `branches`.

    Only `status != 'active'` refuses a row (B6) — a flagged item, a missing
    photo and a null price all publish. A null price becomes 0 and the item is
    named in the report (B7): the report is the mitigation, not a veto.
    """
    items = list(items)
    report = PublishReport()
    publishable = [it for it in items if it.status == 'active']
    cats, created_names = ensure_categories(
        company, branches, [(it.category or '').strip() or 'Menu' for it in publishable])
    report.categories_created = created_names

    used = set()
    for order, it in enumerate(items):
        if it.status != 'active':
            report.skipped.append(it.name)
            continue
        price = it.reference_price if it.reference_price is not None else 0
        if it.reference_price is None:
            report.zero_priced.append(it.name)
        slug = unique_item_slug(company, it.name, taken=used)
        used.add(slug)
        menu_item, created = upsert_menu_item(
            company, branches, slug=slug, name=it.name, description=it.description,
            price=price, dietary_tags=it.dietary_tags,
            category=cats[(it.category or '').strip() or 'Menu'], display_order=order)
        if created:
            report.created += 1
        else:
            report.updated += 1
        if it.image_asset_id and it.image_asset.file:
            src = Path(settings.MEDIA_ROOT) / it.image_asset.file
            if src.exists():
                url, fx, fy = copy_image_to_tenant(company, menu_item.slug, src)
                menu_item.image_url = url
                menu_item.focal_x, menu_item.focal_y = fx, fy
                menu_item.save(update_fields=['image_url', 'focal_x', 'focal_y'])
    return report
