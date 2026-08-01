"""The backfill that turns four live tenants into a library.

Two rules are load-bearing and each has its own test: a rejected asset is never
adopted (two of them are live on a real menu today), and a venue's own
photograph never leaks to another tenant.
"""
import hashlib
from pathlib import Path

import pytest
from django.conf import settings

from menu import library
from menu.models import (Branch, BranchCategory, BranchItemPlacement,
                         BranchMenuItem, Category, Company, ImageAsset, Item,
                         MenuItem)


def _png(marker):
    """Distinct bytes per marker, so each item hashes to its own asset."""
    return b'\x89PNG\r\n\x1a\n' + marker.encode()


def _asset(marker, *, status='verified', prompt='', source='flux'):
    body = _png(marker)
    rel = f'imagelib/{marker}.webp'
    path = Path(settings.MEDIA_ROOT) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return ImageAsset.objects.create(
        name=marker, source=source, file=rel, status=status, prompt=prompt,
        content_hash=hashlib.sha256(body).hexdigest())


def _venue(slug, name='Venue'):
    company = Company.objects.create(name=name, slug=slug)
    branch = Branch.all_objects.create(company=company, name='Main', slug='main')
    return company, branch


def _item(company, branch, *, name, section, price=100, description='',
          dietary_tags=None, body=None):
    """A tenant menu item, placed in a category, optionally with a live image."""
    category, _ = Category.all_objects.get_or_create(
        company=company, slug=section.lower().replace(' ', '-'),
        defaults={'name': section})
    BranchCategory.objects.get_or_create(branch=branch, category=category)
    slug = name.lower().replace(' ', '-').replace('(', '').replace(')', '')
    image_url = ''
    if body is not None:
        rel = f'items/{company.slug}/{slug}.webp'
        path = Path(settings.MEDIA_ROOT) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        image_url = f'{settings.MEDIA_URL}{rel}'
    menu_item = MenuItem.all_objects.create(
        company=company, name=name, slug=slug, price=price,
        description=description, dietary_tags=list(dietary_tags or []),
        image_url=image_url)
    BranchMenuItem.objects.create(branch=branch, menu_item=menu_item)
    BranchItemPlacement.objects.create(branch=branch, menu_item=menu_item,
                                       category=category)
    return menu_item


@pytest.mark.django_db
def test_a_tenant_item_becomes_a_library_entry():
    company, branch = _venue('chillzone', 'Chill Zone')
    asset = _asset('tea', prompt='black tea in a glass, STYLE')
    _item(company, branch, name='Black Tea', section='Hot Drinks', price=60,
          description='strong milk tea', body=_png('tea'))

    report = library.backfill([company])

    entry = Item.objects.get(name='Black Tea')
    assert report.created == 1
    assert entry.status == 'active'
    assert entry.search_name == 'black tea'
    assert entry.category == 'Hot Drinks'
    assert entry.reference_price == 60
    assert entry.description == 'strong milk tea'
    assert entry.image_asset_id == asset.pk
    assert entry.image_prompt == 'black tea in a glass, STYLE'
    assert entry.origin_company_id == company.pk
    assert entry.shareable is True
    assert entry.use_count == 1


@pytest.mark.django_db
def test_an_entry_with_no_asset_prompt_gets_one_composed():
    """Every entry carries a prompt, so a matched item can be re-rolled at gate
    2 without re-deriving anything."""
    company, branch = _venue('chillzone')
    _item(company, branch, name='Veg Momo', section='Snacks')

    report = library.backfill([company])

    entry = Item.objects.get(name='Veg Momo')
    assert report.prompts_composed == 1
    assert entry.image_prompt.startswith('Veg Momo,')
    assert 'steamed pleated dumplings' in entry.image_prompt
    assert 'no garnish' in entry.image_prompt


@pytest.mark.django_db
def test_two_venues_serving_one_dish_share_one_entry():
    one, branch_one = _venue('chillzone')
    two, branch_two = _venue('metro')
    _asset('tea', prompt='black tea, STYLE')
    _item(one, branch_one, name='Black Tea', section='Hot Drinks', price=60,
          body=_png('tea'))
    _item(two, branch_two, name='BLACK TEA', section='Beverages', price=80)

    report = library.backfill([one, two])

    assert Item.objects.filter(status='active').count() == 1
    entry = Item.objects.get(status='active')
    assert report.created == 1 and report.merged == 1
    assert entry.use_count == 2
    assert entry.reference_price == 60          # the first contributor's, not overwritten
    assert entry.image_asset is not None        # the second venue inherits the image


@pytest.mark.django_db
def test_the_spellings_of_one_dish_share_one_entry():
    one, branch_one = _venue('chillzone')
    two, branch_two = _venue('metro')
    _item(one, branch_one, name='Chicken Chow Mein', section='Noodles')
    _item(two, branch_two, name='Chicken Chowmin', section='Noodles')

    library.backfill([one, two])

    assert Item.objects.filter(status='active').count() == 1
    assert Item.objects.get(status='active').search_name == 'chicken chowmein'


@pytest.mark.django_db
def test_two_proteins_of_one_dish_stay_two_entries():
    """The failure that reaches a guest as a dietary or religious violation, not
    merely a wrong picture. It must not even be possible to merge them."""
    company, branch = _venue('chillzone')
    _item(company, branch, name='Steam Momo (Veg)', section='Momo')
    _item(company, branch, name='Steam Momo (Buff)', section='Momo')

    library.backfill([company])

    entries = Item.objects.filter(status='active').order_by('variant_label')
    assert entries.count() == 2
    assert [e.variant_label for e in entries] == ['Buff', 'Veg']
    assert {e.search_name for e in entries} == {'steam momo'}
    assert {e.base_name for e in entries} == {'Steam Momo'}


@pytest.mark.django_db
def test_a_rejected_asset_is_never_adopted_and_is_reported():
    """Two of these are live on Tranquility Inn's menu right now. An entry that
    adopted one would hand that picture to the next venue too."""
    company, branch = _venue('tranquility-inn')
    _asset('lemon', status='rejected', prompt='lemon soda, STYLE')
    _item(company, branch, name='Lemon Soda', section='Soft Drinks',
          body=_png('lemon'))

    report = library.backfill([company])

    entry = Item.objects.get(name='Lemon Soda')
    assert entry.image_asset_id is None
    assert entry.image_prompt.startswith('Lemon Soda,')     # composed, not the rejected one's
    assert entry.shareable is True                          # rejected != a venue photograph
    assert len(report.rejected_live) == 1
    assert 'lemon-soda' in report.rejected_live[0]


@pytest.mark.django_db
def test_a_venue_supplied_photograph_is_not_shareable():
    """Founder, spec D2: it is the venue's property. Its entry is scoped to that
    venue and never matches for another tenant."""
    company, branch = _venue('tranquility-inn')
    _item(company, branch, name='Simple Breakfast', section='Breakfast',
          body=_png('their-own-photo'))       # no pool asset hashes to this

    report = library.backfill([company])

    entry = Item.objects.get(name='Simple Breakfast')
    assert report.venue_photos == 1
    assert entry.shareable is False
    assert entry.origin_company_id == company.pk


@pytest.mark.django_db
def test_a_non_shareable_entry_is_never_merged_with_another_venues_row():
    one, branch_one = _venue('tranquility-inn')
    two, branch_two = _venue('chillzone')
    _item(one, branch_one, name='Simple Breakfast', section='Breakfast',
          body=_png('their-own-photo'))
    _item(two, branch_two, name='Simple Breakfast', section='Breakfast')

    library.backfill([one, two])

    entries = Item.objects.filter(status='active', search_name='simple breakfast')
    assert entries.count() == 2
    assert sorted(e.shareable for e in entries) == [False, True]
    assert all(e.use_count == 1 for e in entries)


@pytest.mark.django_db
def test_an_item_with_no_image_still_becomes_an_entry():
    company, branch = _venue('chillzone')
    _item(company, branch, name='Plain Rice', section='Rice')

    library.backfill([company])

    entry = Item.objects.get(name='Plain Rice')
    assert entry.image_asset_id is None
    assert entry.shareable is True         # nothing to leak
    assert entry.image_prompt


@pytest.mark.django_db
def test_running_twice_changes_nothing():
    """The backfill is resumable and re-runnable: it must not grow the library
    or double a count."""
    company, branch = _venue('chillzone')
    _asset('tea', prompt='black tea, STYLE')
    _item(company, branch, name='Black Tea', section='Hot Drinks', body=_png('tea'))

    library.backfill([company])
    before = list(Item.objects.filter(status='active')
                  .values_list('pk', 'use_count', 'image_asset_id'))
    second = library.backfill([company])

    assert second.created == 0
    assert list(Item.objects.filter(status='active')
                .values_list('pk', 'use_count', 'image_asset_id')) == before


@pytest.mark.django_db
def test_a_merge_fills_gaps_but_never_overwrites():
    one, branch_one = _venue('chillzone')
    two, branch_two = _venue('metro')
    _item(one, branch_one, name='Veg Thali', section='Thali', price=250)
    _asset('thali', prompt='veg thali, STYLE')
    _item(two, branch_two, name='Veg Thali', section='Thali', price=300,
          description='rice, dal and two curries', dietary_tags=['veg'],
          body=_png('thali'))

    library.backfill([one, two])

    entry = Item.objects.get(status='active')
    assert entry.reference_price == 250                       # first venue's, kept
    assert entry.description == 'rice, dal and two curries'    # gap, filled
    assert entry.dietary_tags == ['veg']                       # gap, filled
    assert entry.image_asset is not None                       # gap, filled
    assert entry.image_prompt == 'veg thali, STYLE'            # gap, filled


@pytest.mark.django_db
def test_an_item_with_no_placement_is_reported_not_guessed_at():
    company = Company.objects.create(name='Odd', slug='odd')
    MenuItem.all_objects.create(company=company, name='Orphan', slug='orphan', price=10)

    report = library.backfill([company])

    assert Item.objects.filter(status='active').count() == 0
    assert report.no_placement == ['odd/orphan']


@pytest.mark.django_db
def test_draft_rows_from_the_scan_flow_are_not_treated_as_library_entries():
    """126 stale drafts sit in this table. They are not the library and must
    not absorb a venue's item."""
    Item.objects.create(name='Black Tea', status='draft', search_name='black tea')
    company, branch = _venue('chillzone')
    _item(company, branch, name='Black Tea', section='Hot Drinks')

    library.backfill([company])

    assert Item.objects.filter(status='active').count() == 1
    assert Item.objects.filter(status='draft').count() == 1
