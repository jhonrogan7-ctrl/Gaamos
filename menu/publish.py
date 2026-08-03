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
    # Filled by `builds.publish_build` only: `publish_rows` writes the tenant
    # menu, growing the library is the wizard's own step.
    library_created: int = 0
    library_reused: int = 0


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

    A blank `icon_key` is treated as "no opinion" rather than "clear it", so a
    fixture with no icons cannot wipe icons the venue set in the dashboard.
    """
    fields = {'name': name, 'display_order': display_order,
              'hours_note': hours_note}
    # A blank icon_key means "no opinion", not "clear it". Every fixture
    # generated before category_icons existed carries `icon_key: ""`, and
    # re-importing a live venue is routine — without this, adding a second
    # card to a tenant would wipe every icon its owner had chosen.
    if icon_key:
        fields['icon_key'] = icon_key
    create_fields = {**fields, 'icon_key': icon_key}
    if update:
        cat, created = Category.all_objects.update_or_create(
            company=company, slug=slug or slugify(name)[:50],
            defaults=fields, create_defaults=create_fields)
    else:
        cat, created = Category.all_objects.get_or_create(
            company=company, slug=slug or slugify(name)[:50],
            defaults=create_fields)
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


@dataclass
class PublishRow:
    """One row on its way into a tenant menu.

    Deliberately not a model and not a catalog `Item`: the wizard's rows, the
    fixture importer and the scan workbench all publish, and they agree on this
    shape rather than on each other's storage.

    `price` is the price PRINTED ON THIS VENUE'S CARD. A catalog entry's
    `reference_price` belongs to whichever venue contributed it first, and
    publishing that onto another venue's menu is the defect this record exists
    to prevent.
    """
    name: str
    price: int = None
    description: str = ''
    dietary_tags: list = field(default_factory=list)
    category: str = 'Menu'
    category_icon: str = ''
    image_asset: object = None
    publishable: bool = True


def publish_items(company, branches, items):
    """Publish catalog `Item`s into `company`'s menu on `branches`.

    Kept for the fixture importer and the scan workbench, which both hold
    `Item`s rather than printed rows. A thin adapter over `publish_rows` so
    there is still exactly one writer.

    Note it passes `reference_price` — correct here, because these callers have
    no printed row to read a price from; the wizard does, and uses it.
    """
    rows = [PublishRow(name=it.name, price=it.reference_price,
                       description=it.description,
                       dietary_tags=list(it.dietary_tags or []),
                       category=(it.category or '').strip() or 'Menu',
                       image_asset=it.image_asset if it.image_asset_id else None,
                       publishable=(it.status == 'active'))
            for it in items]
    return publish_rows(company, branches, rows)


def publish_rows(company, branches, rows):
    """Publish printed rows into `company`'s menu on `branches`.

    Only an unpublishable row is refused (B6) — a flagged item, a missing photo
    and a null price all publish. A null price becomes 0 and the row is named in
    the report (B7): the report is the mitigation, not a veto.
    """
    rows = list(rows)
    report = PublishReport()
    publishable = [r for r in rows if r.publishable]
    cats, created_names = ensure_categories(
        company, branches, [(r.category or '').strip() or 'Menu' for r in publishable])
    report.categories_created = created_names

    for row in publishable:
        icon = (row.category_icon or '').strip()
        if icon:
            category = cats[(row.category or '').strip() or 'Menu']
            if category.icon_key != icon:
                category.icon_key = icon
                category.save(update_fields=['icon_key'])

    used = set()
    for order, row in enumerate(rows):
        if not row.publishable:
            report.skipped.append(row.name)
            continue
        price = row.price if row.price is not None else 0
        if row.price is None:
            report.zero_priced.append(row.name)
        slug = unique_item_slug(company, row.name, taken=used)
        used.add(slug)
        menu_item, created = upsert_menu_item(
            company, branches, slug=slug, name=row.name,
            description=row.description, price=price,
            dietary_tags=row.dietary_tags,
            category=cats[(row.category or '').strip() or 'Menu'],
            display_order=order)
        if created:
            report.created += 1
        else:
            report.updated += 1
        if row.image_asset is not None and row.image_asset.file:
            src = Path(settings.MEDIA_ROOT) / row.image_asset.file
            if src.exists():
                url, fx, fy = copy_image_to_tenant(company, menu_item.slug, src)
                menu_item.image_url = url
                menu_item.focal_x, menu_item.focal_y = fx, fy
                menu_item.save(update_fields=['image_url', 'focal_x', 'focal_y'])
    return report
