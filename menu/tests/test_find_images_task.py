from unittest.mock import patch

import pytest

from menu.models import ImageAsset, Item, MenuScan
from menu.tasks import find_images_for_scan

HIT = [{'asset_id': None, 'file': 'imagelib/a.webp', 'name': 'Tea',
        'caption': 'Black Tea', 'similarity': 0.91}]
CANDS = [{'url': 'https://img/tea.jpg', 'page': 'https://pexels.com/p/tea/',
          'credit': 'Someone', 'source': 'pexels'}]


def _scan():
    return MenuScan.objects.create(file='scans/x.pdf', status='extracted')


def _item(scan, name='Black Tea', **kw):
    kw.setdefault('status', 'draft')
    kw.setdefault('tags', ['black', 'tea'])
    return Item.objects.create(source_scan=scan, name=name, raw_name=name, **kw)


@pytest.mark.django_db
def test_library_hit_attaches_the_verified_asset_without_downloading():
    scan = _scan()
    item = _item(scan)
    asset = ImageAsset.objects.create(source='pexels', status='verified',
                                      file='imagelib/a.webp', caption='Black Tea')
    hit = [dict(HIT[0], asset_id=asset.pk)]
    with patch('menu.pipeline.find_library.search', return_value=hit), \
         patch('menu.pipeline.photo_search.search') as search, \
         patch('menu.pipeline.intake.record') as record:
        find_images_for_scan(scan.pk)
    item.refresh_from_db()
    assert item.image_asset_id == asset.pk
    search.assert_not_called()
    record.assert_not_called()


@pytest.mark.django_db
def test_library_miss_downloads_records_pending_and_attaches():
    scan = _scan()
    item = _item(scan)
    new_asset = ImageAsset.objects.create(source='pexels', status='pending',
                                          file='imagelib/new.webp')
    with patch('menu.pipeline.find_library.search', return_value=[]), \
         patch('menu.pipeline.photo_search.search', return_value=list(CANDS)), \
         patch('menu.pipeline.photo_search.fetch_thumbnail', return_value=b'WEBP') as fetch, \
         patch('menu.pipeline.intake.record', return_value=new_asset) as record:
        find_images_for_scan(scan.pk)
    item.refresh_from_db()
    assert item.image_asset_id == new_asset.pk
    fetch.assert_called_once_with('pexels', 'https://img/tea.jpg')
    kwargs = record.call_args.kwargs
    assert kwargs['webp_bytes'] == b'WEBP'
    assert kwargs['item_name'] == 'Black Tea'
    assert kwargs['origin_url'] == 'https://pexels.com/p/tea/'
    assert kwargs['tags'] == ['black', 'tea']      # the library gets searchable at deposit
    assert kwargs['found_for_slug'] == 'black-tea'


@pytest.mark.django_db
def test_item_that_finds_nothing_is_left_alone():
    scan = _scan()
    item = _item(scan)
    with patch('menu.pipeline.find_library.search', return_value=[]), \
         patch('menu.pipeline.photo_search.search', return_value=[]), \
         patch('menu.pipeline.intake.record') as record:
        find_images_for_scan(scan.pk)
    item.refresh_from_db()
    assert item.image_asset_id is None
    record.assert_not_called()


@pytest.mark.django_db
def test_a_rejected_tombstone_leaves_the_item_empty():
    """intake.record returns None for a source we already rejected."""
    scan = _scan()
    item = _item(scan)
    with patch('menu.pipeline.find_library.search', return_value=[]), \
         patch('menu.pipeline.photo_search.search', return_value=list(CANDS)), \
         patch('menu.pipeline.photo_search.fetch_thumbnail', return_value=b'WEBP'), \
         patch('menu.pipeline.intake.record', return_value=None):
        find_images_for_scan(scan.pk)
    item.refresh_from_db()
    assert item.image_asset_id is None


@pytest.mark.django_db
def test_items_that_already_have_an_image_are_skipped():
    scan = _scan()
    asset = ImageAsset.objects.create(source='pexels', status='verified',
                                      file='imagelib/a.webp')
    item = _item(scan, image_asset=asset)
    with patch('menu.pipeline.find_library.search') as lib:
        find_images_for_scan(scan.pk)
    lib.assert_not_called()
    item.refresh_from_db()
    assert item.image_asset_id == asset.pk


@pytest.mark.django_db
def test_rejected_and_merged_rows_are_not_given_photos():
    scan = _scan()
    keeper = _item(scan, name='Keeper', status='active')
    dead = _item(scan, name='Ghost', status='rejected')
    gone = _item(scan, name='Dup', status='merged', merged_into=keeper)
    with patch('menu.pipeline.find_library.search', return_value=[]), \
         patch('menu.pipeline.photo_search.search', return_value=[]) as search:
        find_images_for_scan(scan.pk)
    dead.refresh_from_db()
    gone.refresh_from_db()
    assert dead.image_asset_id is None
    assert gone.image_asset_id is None
    assert search.call_count == 1          # only the active keeper was searched


@pytest.mark.django_db
def test_one_failing_item_does_not_abandon_the_rest():
    """A dead photo URL must not cost the whole scan its images."""
    scan = _scan()
    _item(scan, name='Aaa')
    _item(scan, name='Bbb')
    good = ImageAsset.objects.create(source='pexels', status='pending',
                                     file='imagelib/g.webp')
    calls = {'n': 0}

    def flaky(source, url, size=800):
        calls['n'] += 1
        if calls['n'] == 1:
            raise RuntimeError('404 from source')
        return b'WEBP'

    with patch('menu.pipeline.find_library.search', return_value=[]), \
         patch('menu.pipeline.photo_search.search', return_value=list(CANDS)), \
         patch('menu.pipeline.photo_search.fetch_thumbnail', side_effect=flaky), \
         patch('menu.pipeline.intake.record', return_value=good):
        find_images_for_scan(scan.pk)
    assert Item.objects.filter(source_scan=scan,
                               image_asset__isnull=False).count() == 1
