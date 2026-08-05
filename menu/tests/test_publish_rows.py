"""Publishing from a printed row rather than a catalog entry.

The one rule this file exists for: the price that reaches a guest is the price
printed on the venue's own card, never the library's reference price -- which
belongs to whichever venue happened to contribute the entry first.
"""
from pathlib import Path

import pytest

from menu import publish
from menu.models import Branch, Company, ImageAsset, Item, MenuItem


@pytest.fixture
def company(db):
    c = Company.objects.create(name='Kailash Parbat', slug='kailash')
    Branch.all_objects.create(company=c, name='Lakeside', slug='lakeside')
    return c


@pytest.fixture
def branches(company):
    return list(Branch.all_objects.filter(company=company))


@pytest.mark.django_db
def test_a_row_publishes_its_own_price(company, branches):
    row = publish.PublishRow(name='Black Tea', price=60, category='Hot Drinks')

    publish.publish_rows(company, branches, [row])

    assert MenuItem.all_objects.get(company=company, name='Black Tea').price == 60


@pytest.mark.django_db
def test_the_printed_price_beats_the_library_reference_price(company, branches):
    """The defect this refactor exists to prevent. The library says 120 because
    another venue served it at 120; this venue's card says 60."""
    entry = Item.objects.create(name='Black Tea', status='active',
                                reference_price=120, category='Hot Drinks')
    row = publish.PublishRow(name='Black Tea', price=60, category='Hot Drinks')

    publish.publish_rows(company, branches, [row])

    assert MenuItem.all_objects.get(company=company, name='Black Tea').price == 60
    assert entry.reference_price == 120     # the library is not rewritten either


@pytest.mark.django_db
def test_a_null_price_publishes_as_zero_and_is_reported(company, branches):
    row = publish.PublishRow(name='Market Fish', price=None, category='Fish')

    report = publish.publish_rows(company, branches, [row])

    assert MenuItem.all_objects.get(company=company, name='Market Fish').price == 0
    assert report.zero_priced == ['Market Fish']


@pytest.mark.django_db
def test_republishing_updates_rather_than_duplicates(company, branches):
    """The property the whole 'publish now, add images later' workflow rests on."""
    publish.publish_rows(company, branches,
                         [publish.PublishRow(name='Black Tea', price=60)])
    report = publish.publish_rows(company, branches,
                                  [publish.PublishRow(name='Black Tea', price=80)])

    assert MenuItem.all_objects.filter(company=company).count() == 1
    assert report.updated == 1
    assert report.created == 0
    assert MenuItem.all_objects.get(company=company, name='Black Tea').price == 80


@pytest.mark.django_db
def test_a_row_carries_its_category_icon(company, branches):
    from menu.models import Category
    row = publish.PublishRow(name='Veg Momo', price=180, category='Momo',
                             category_icon='momo')

    publish.publish_rows(company, branches, [row])

    assert Category.all_objects.get(company=company, name='Momo').icon_key == 'momo'


@pytest.mark.django_db
def test_an_unpublishable_row_is_skipped_and_named(company, branches):
    row = publish.PublishRow(name='Draft Thing', price=10, publishable=False)

    report = publish.publish_rows(company, branches, [row])

    assert report.skipped == ['Draft Thing']
    assert MenuItem.all_objects.filter(company=company).count() == 0


@pytest.mark.django_db
def test_an_image_asset_is_copied_to_the_tenant(company, branches, tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    rel = 'imagelib/tea.webp'
    src = Path(tmp_path) / rel
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b'WEBPBYTES')
    asset = ImageAsset.objects.create(source='flux', status='verified', file=rel)
    row = publish.PublishRow(name='Black Tea', price=60, image_asset=asset)

    publish.publish_rows(company, branches, [row])

    assert MenuItem.all_objects.get(company=company, name='Black Tea').image_url
