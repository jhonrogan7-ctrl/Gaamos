"""Backfill the global item library from the tenants that already exist.

598 items across four live venues are this platform's only real catalog, and
until this runs they are tenant `MenuItem` rows with no connection to the
`ImageAsset` that drew them. This turns them into `Item` library entries: one
entry per distinct printed name, carrying its image, its prompt, and how many
venues serve it.

Two rules are not negotiable.

* **A rejected asset is never adopted.** 531 of the 557 live images hash-match a
  pool asset, and two of those matches are images a reviewer rejected -- live on
  Tranquility Inn's menu today. An entry that adopted one would hand that
  picture to every venue that follows.
* **A venue-supplied photograph is not shareable** (founder, spec D2). It is the
  venue's property: its entry is scoped to that venue and never matches for
  another tenant.

The image link is made by content hash rather than by filename, because the
tenant copy under `items/<company>/…` was renamed on its way in and only the
bytes still agree.
"""
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

from menu.models import BranchItemPlacement, ImageAsset, Item, MenuItem
from menu.pipeline import name_norm, prompts


@dataclass
class BackfillReport:
    created: int = 0
    merged: int = 0
    venue_photos: int = 0
    prompts_composed: int = 0
    rejected_live: list = field(default_factory=list)
    no_placement: list = field(default_factory=list)
    cleared_live: list = field(default_factory=list)
    reconciled: list = field(default_factory=list)


def asset_index():
    """content_hash -> ImageAsset, for every pool asset that has one.

    `content_hash` is uniquely constrained, so this is one asset per hash.
    """
    return {a.content_hash: a for a in ImageAsset.objects.exclude(content_hash='')}


def _live_image(menu_item, index):
    """-> (asset, has_image, rejected_asset) for a tenant item's live picture.

    `asset` is None when there is nothing usable to adopt -- no image, an image
    the pool does not know (the venue's own photograph), or an image whose pool
    row a reviewer rejected. The three cases are told apart by the other two
    values, because they mean opposite things for `shareable`.
    """
    if not menu_item.image_url:
        return None, False, None
    rel = menu_item.image_url.replace(settings.MEDIA_URL, '', 1)
    path = Path(settings.MEDIA_ROOT) / rel
    if not path.exists():
        return None, False, None
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    asset = index.get(digest)
    if asset is None:
        return None, True, None
    if asset.status == 'rejected':
        return None, True, asset
    return asset, True, None


def _section(menu_item):
    """The venue's own section name, in its own words -- `KAILASH TOUCH` stays."""
    placement = (BranchItemPlacement.objects.filter(menu_item=menu_item)
                 .select_related('category')
                 .order_by('category__display_order', 'display_order').first())
    return placement.category.name if placement else ''


def _find_entry(search_name, variant, scope):
    """An existing library entry for this key, or None.

    `scope` is None for a shareable entry and the origin company's pk for one
    that is not: a venue's own photograph forms its own entry rather than
    merging with anybody else's row.
    """
    for candidate in Item.objects.filter(status='active', search_name=search_name):
        if name_norm.normalize(candidate.variant_label) != variant:
            continue
        candidate_scope = None if candidate.shareable else candidate.origin_company_id
        if candidate_scope == scope:
            return candidate
    return None


def _create_entry(menu_item, *, company, section, asset, shareable, search_name,
                  report):
    base, variant = name_norm.split_variant(menu_item.name)
    if asset is not None and asset.prompt:
        prompt = asset.prompt
    else:
        prompt = prompts.for_item(menu_item.name, section)
        report.prompts_composed += 1
    return Item.objects.create(
        name=menu_item.name,
        base_name=base if variant else '',
        variant_label=variant,
        search_name=search_name,
        description=menu_item.description,
        category=section,
        dietary_tags=list(menu_item.dietary_tags or []),
        reference_price=menu_item.price,
        currency='NPR',
        image_asset=asset,
        image_prompt=prompt,
        origin_company=company,
        shareable=shareable,
        status='active',
        use_count=1)


def _merge_into(entry, *, asset, description, dietary_tags, price):
    """Fill this entry's gaps from another row. Never overwrite.

    The fields are passed one by one rather than as an object because the two
    callers hand over different shapes -- a tenant `MenuItem` (`price`) and an
    older catalog `Item` (`reference_price`) -- and a duck-typed `.price` would
    read whichever attribute happened to exist.

    The first venue to contribute a dish owns the entry's text: a later venue's
    wording is not more correct, and the printed row price wins at publish time
    anyway (spec D5), so `reference_price` here is a hint and nothing more.
    """
    changed = []
    if asset is not None and entry.image_asset_id is None:
        entry.image_asset = asset
        changed.append('image_asset')
        # An entry that had no image can only be carrying a prompt this module
        # composed from the printed name, never one that drew a picture. The
        # adopted asset's prompt describes the image the entry now shows, so it
        # replaces the placeholder -- otherwise a re-roll at gate 2 would
        # produce something the guest was never shown.
        if asset.prompt:
            entry.image_prompt = asset.prompt
            changed.append('image_prompt')
    if description and not entry.description:
        entry.description = description
        changed.append('description')
    if dietary_tags and not entry.dietary_tags:
        entry.dietary_tags = list(dietary_tags)
        changed.append('dietary_tags')
    if entry.reference_price is None and price is not None:
        entry.reference_price = price
        changed.append('reference_price')
    if changed:
        entry.save(update_fields=changed)


def reconcile_stray_entries(report):
    """Give a pre-backfill `active` row the key the library compares on.

    The scan-review flow could approve an item into this table before it was a
    library, so those rows carry no `search_name` and the matcher cannot see
    them. Deriving one is mechanical -- it comes from the row's own printed
    name. What it can reveal is that the row duplicates an entry the backfill
    built from a real venue's menu, and two `active` rows on one key would make
    the matcher return an arbitrary one of them. The duplicate is folded into
    the venue-grounded entry with the model's own `merged` / `merged_into`
    vocabulary: nothing is deleted, and the older row keeps its provenance.
    """
    for entry in Item.objects.filter(status='active', search_name=''):
        # `category` is where `_create_entry` wrote the section, so a stray row
        # is re-keyed by the same rule the backfill uses.
        entry.search_name = name_norm.search_form(entry.name, entry.category)
        if not entry.image_prompt:
            entry.image_prompt = prompts.for_item(entry.name, entry.category)
        variant = name_norm.normalize(entry.variant_label)
        keeper = next(
            (c for c in Item.objects.filter(status='active',
                                            search_name=entry.search_name)
             .exclude(pk=entry.pk)
             if name_norm.normalize(c.variant_label) == variant), None)
        if keeper is None:
            entry.save(update_fields=['search_name', 'image_prompt'])
            report.reconciled.append(f'#{entry.pk} {entry.name} -> keyed')
            continue
        _merge_into(keeper, asset=entry.image_asset,
                    description=entry.description,
                    dietary_tags=entry.dietary_tags,
                    price=entry.reference_price)
        entry.status = 'merged'
        entry.merged_into = keeper
        entry.save(update_fields=['search_name', 'image_prompt', 'status',
                                  'merged_into'])
        report.reconciled.append(
            f'#{entry.pk} {entry.name} -> merged into #{keeper.pk} {keeper.name}')


def backfill(companies, *, index=None, clear_rejected_live=False):
    """Walk each company's menu and record it in the library.

    Idempotent: a second run finds every entry it made and merges into it,
    changing nothing. `use_count` is SET from the venues in this run rather than
    incremented, so re-running cannot inflate it -- pass every venue at once.
    """
    index = asset_index() if index is None else index
    report = BackfillReport()
    contributors = defaultdict(set)

    for company in companies:
        for menu_item in MenuItem.all_objects.filter(company=company).order_by('slug'):
            section = _section(menu_item)
            if not section:
                report.no_placement.append(f'{company.slug}/{menu_item.slug}')
                continue

            asset, has_image, rejected = _live_image(menu_item, index)
            if rejected is not None:
                report.rejected_live.append(
                    f'{company.slug}/{menu_item.slug} -> rejected asset #{rejected.pk}')
                if clear_rejected_live:
                    menu_item.image_url = ''
                    menu_item.focal_x, menu_item.focal_y = 50, 50
                    menu_item.save(update_fields=['image_url', 'focal_x', 'focal_y'])
                    report.cleared_live.append(f'{company.slug}/{menu_item.slug}')

            venue_photo = has_image and asset is None and rejected is None
            if venue_photo:
                report.venue_photos += 1
            shareable = not venue_photo

            # The section, not just the name: a printed name is not unique
            # within one card. `Apple` appears under both JUICE and MILK SHAKE
            # / LASSI on the Kailash Parbat menu at the same price.
            search_name, variant = name_norm.entry_key(menu_item.name, section)
            scope = None if shareable else company.pk
            entry = _find_entry(search_name, variant, scope)
            if entry is None:
                entry = _create_entry(menu_item, company=company, section=section,
                                      asset=asset, shareable=shareable,
                                      search_name=search_name, report=report)
                report.created += 1
            else:
                _merge_into(entry, asset=asset,
                            description=menu_item.description,
                            dietary_tags=menu_item.dietary_tags,
                            price=menu_item.price)
                report.merged += 1
            contributors[entry.pk].add(company.pk)

    for pk, venues in contributors.items():
        Item.objects.filter(pk=pk).update(use_count=len(venues))
    # Last, so a stray row is compared against the entries this run just built
    # rather than against whatever happened to exist first.
    reconcile_stray_entries(report)
    return report
