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


from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError


@pytest.mark.django_db
def test_the_command_backfills_the_named_companies():
    company, branch = _venue('chillzone')
    _item(company, branch, name='Black Tea', section='Hot Drinks')
    out = StringIO()

    call_command('build_library', '--company', 'chillzone', stdout=out)

    assert Item.objects.filter(status='active').count() == 1
    assert 'created 1' in out.getvalue()


@pytest.mark.django_db
def test_an_unknown_company_slug_is_an_error_not_a_silent_no_op():
    with pytest.raises(CommandError, match='nosuchvenue'):
        call_command('build_library', '--company', 'nosuchvenue')


@pytest.mark.django_db
def test_dry_run_writes_nothing():
    company, branch = _venue('chillzone')
    _item(company, branch, name='Black Tea', section='Hot Drinks')
    out = StringIO()

    call_command('build_library', '--company', 'chillzone', '--dry-run', stdout=out)

    assert Item.objects.filter(status='active').count() == 0
    assert 'created 1' in out.getvalue()
    assert 'rolled back' in out.getvalue()


@pytest.mark.django_db
def test_prune_drafts_removes_the_scan_flows_stale_rows_only():
    Item.objects.create(name='Stale Draft', status='draft')
    Item.objects.create(name='Live Entry', status='active')
    out = StringIO()
    company, branch = _venue('chillzone')

    call_command('build_library', '--company', 'chillzone', '--prune-drafts', stdout=out)

    assert Item.objects.filter(status='draft').count() == 0
    assert Item.objects.filter(name='Live Entry').exists()
    assert 'pruned 1 draft' in out.getvalue()


@pytest.mark.django_db
def test_clear_rejected_live_takes_the_rejected_picture_off_the_live_menu():
    """A wrong photograph is a claim the guest orders from. Blank beats wrong."""
    company, branch = _venue('tranquility-inn')
    _asset('lemon', status='rejected')
    menu_item = _item(company, branch, name='Lemon Soda', section='Soft Drinks',
                      body=_png('lemon'))
    out = StringIO()

    call_command('build_library', '--company', 'tranquility-inn',
                 '--clear-rejected-live', stdout=out)

    menu_item.refresh_from_db()
    assert menu_item.image_url == ''
    assert 'cleared 1' in out.getvalue()


@pytest.mark.django_db
def test_without_the_flag_the_rejected_picture_is_reported_but_left_alone():
    company, branch = _venue('tranquility-inn')
    _asset('lemon', status='rejected')
    menu_item = _item(company, branch, name='Lemon Soda', section='Soft Drinks',
                      body=_png('lemon'))
    out = StringIO()

    call_command('build_library', '--company', 'tranquility-inn', stdout=out)

    menu_item.refresh_from_db()
    assert menu_item.image_url != ''
    assert 'rejected asset' in out.getvalue()


@pytest.mark.django_db
def test_a_row_that_predates_the_library_gets_the_key_the_matcher_compares_on():
    """The scan-review flow could approve an item into this table before it was
    a library, so those rows carry no search_name and the matcher cannot see
    them."""
    stray = Item.objects.create(name='Ruslan Vodka 60ml', base_name='Ruslan Vodka',
                                variant_label='60ml', category='HARD DRINKS',
                                status='active', reference_price=300)
    company, branch = _venue('chillzone')
    _item(company, branch, name='Black Tea', section='Hot Drinks')

    report = library.backfill([company])

    stray.refresh_from_db()
    assert stray.status == 'active'
    assert stray.search_name == 'ruslan vodka'
    assert stray.image_prompt                       # composed from its own name
    assert 'Ruslan Vodka 60ml -> keyed' in report.reconciled[0]


@pytest.mark.django_db
def test_a_stray_row_that_duplicates_a_real_entry_is_merged_not_left_active():
    """Two active rows on one key would make the matcher return an arbitrary one
    of them. The venue-grounded entry keeps the key; the older row is folded in
    with the model's own vocabulary, and nothing is deleted."""
    stray = Item.objects.create(name='8848 Vodka 60ml', base_name='8848 Vodka',
                                variant_label='60ml', category='HARD DRINKS',
                                status='active', reference_price=300)
    company, branch = _venue('chillzone')
    _item(company, branch, name='8848 Vodka (60ml)', section='Hard Drinks', price=300)

    library.backfill([company])

    stray.refresh_from_db()
    keeper = Item.objects.get(status='active', search_name='8848 vodka')
    assert stray.status == 'merged'
    assert stray.merged_into_id == keeper.pk
    assert keeper.name == '8848 Vodka (60ml)'       # the one a real venue prints
    assert Item.objects.filter(status='active', search_name='8848 vodka').count() == 1


@pytest.mark.django_db
def test_a_stray_row_fills_the_keepers_gaps_before_it_is_merged_away():
    """Its image is the only copy of that picture the library has."""
    asset = _asset('vodka', prompt='a shot of vodka, STYLE')
    stray = Item.objects.create(name='8848 Vodka 60ml', variant_label='60ml',
                                status='active', image_asset=asset,
                                description='a nip of the local vodka')
    company, branch = _venue('chillzone')
    _item(company, branch, name='8848 Vodka (60ml)', section='Hard Drinks')

    library.backfill([company])

    stray.refresh_from_db()
    keeper = Item.objects.get(status='active', search_name='8848 vodka')
    assert stray.status == 'merged'
    assert keeper.image_asset_id == asset.pk
    assert keeper.description == 'a nip of the local vodka'


@pytest.mark.django_db
def test_reconciling_leaves_a_healthy_library_alone():
    """Every entry the backfill writes already has a search_name, so a second
    run must find nothing to reconcile."""
    company, branch = _venue('chillzone')
    _item(company, branch, name='Black Tea', section='Hot Drinks')

    library.backfill([company])
    second = library.backfill([company])

    assert second.reconciled == []
