from pathlib import Path

import pytest

from menu import publish
from menu.models import (Branch, BranchCategory, BranchItemPlacement, BranchMenuItem,
                         Category, Company, ImageAsset, Item, MenuItem)
from menu.tenancy import reset_current_company, set_current_company


@pytest.fixture
def company(db):
    c = Company.objects.create(name='Kailash Parbat', slug='kailash')
    Branch.all_objects.create(company=c, name='Thamel', slug='thamel')
    return c


@pytest.fixture
def branches(company):
    return list(Branch.all_objects.filter(company=company))


def _item(name, **kw):
    kw.setdefault('status', 'active')
    kw.setdefault('category', 'Hot Drinks')
    kw.setdefault('reference_price', 120)
    return Item.objects.create(name=name, raw_name=name, **kw)


def _asset(tmp_path, settings, body=b'WEBPBYTES'):
    # The pytest-django `settings` fixture restores MEDIA_ROOT after the test —
    # assigning `django.conf.settings` directly would leak into the rest of the
    # session and quietly relocate every later test's media writes.
    settings.MEDIA_ROOT = str(tmp_path)
    rel = 'imagelib/abc.webp'
    dest = Path(tmp_path) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return ImageAsset.objects.create(source='pexels', status='verified', file=rel)


@pytest.mark.django_db
def test_categories_are_created_in_printed_order(company, branches):
    names = ['Hard Drinks', 'Soft Drinks', 'Hard Drinks', 'Snacks']
    token = set_current_company(company)
    try:
        cats, created = publish.ensure_categories(company, branches, names)
    finally:
        reset_current_company(token)
    assert created == ['Hard Drinks', 'Soft Drinks', 'Snacks']
    assert [c.display_order for c in
            (cats['Hard Drinks'], cats['Soft Drinks'], cats['Snacks'])] == [0, 1, 2]
    assert BranchCategory.objects.filter(branch=branches[0]).count() == 3


@pytest.mark.django_db
def test_ensure_categories_is_idempotent(company, branches):
    token = set_current_company(company)
    try:
        publish.ensure_categories(company, branches, ['Hot Drinks'])
        cats, created = publish.ensure_categories(company, branches, ['Hot Drinks'])
    finally:
        reset_current_company(token)
    assert created == []
    assert Category.all_objects.filter(company=company).count() == 1
    assert cats['Hot Drinks'].name == 'Hot Drinks'


@pytest.mark.django_db
def test_venue_section_names_are_kept_verbatim(company, branches):
    """B5 — 'KAILASH TOUCH' is the venue's brand, not a thing to prettify."""
    token = set_current_company(company)
    try:
        cats, _ = publish.ensure_categories(company, branches, ['KAILASH TOUCH'])
    finally:
        reset_current_company(token)
    assert cats['KAILASH TOUCH'].name == 'KAILASH TOUCH'
    assert cats['KAILASH TOUCH'].slug == 'kailash-touch'


@pytest.mark.django_db
def test_publish_creates_menu_items_linked_to_every_branch(company, branches):
    items = [_item('Black Tea'), _item('Masala Tea')]
    token = set_current_company(company)
    try:
        report = publish.publish_items(company, branches, items)
    finally:
        reset_current_company(token)
    assert report.created == 2
    assert report.updated == 0
    assert MenuItem.all_objects.filter(company=company).count() == 2
    assert BranchMenuItem.objects.filter(branch=branches[0]).count() == 2
    assert BranchItemPlacement.objects.filter(branch=branches[0]).count() == 2


@pytest.mark.django_db
def test_null_price_publishes_at_zero_and_is_named_in_the_report(company, branches):
    """B7 — the item goes live orderable at Rs 0; the report is the mitigation."""
    items = [_item('Pancake Banana', reference_price=None)]
    token = set_current_company(company)
    try:
        report = publish.publish_items(company, branches, items)
    finally:
        reset_current_company(token)
    assert MenuItem.all_objects.get(company=company).price == 0
    assert report.zero_priced == ['Pancake Banana']


@pytest.mark.django_db
def test_only_non_active_rows_are_skipped(company, branches):
    """B6 — needs_review, no photo and a null price do NOT refuse a publish."""
    flagged = _item('Flagged', needs_review=True, reference_price=None)
    draft = _item('Still A Draft', status='draft')
    items = [flagged, draft]
    token = set_current_company(company)
    try:
        report = publish.publish_items(company, branches, items)
    finally:
        reset_current_company(token)
    assert report.skipped == ['Still A Draft']
    assert MenuItem.all_objects.filter(company=company).count() == 1


@pytest.mark.django_db
def test_republish_upserts_rather_than_duplicating(company, branches):
    item = _item('Black Tea')
    token = set_current_company(company)
    try:
        publish.publish_items(company, branches, [item])
        item.reference_price = 140
        item.save(update_fields=['reference_price'])
        report = publish.publish_items(company, branches, [item])
    finally:
        reset_current_company(token)
    assert report.created == 0
    assert report.updated == 1
    assert MenuItem.all_objects.filter(company=company).count() == 1
    assert MenuItem.all_objects.get(company=company).price == 140


@pytest.mark.django_db
def test_image_is_copied_into_tenant_media_under_the_company_slug(company, branches,
                                                                 tmp_path, settings):
    asset = _asset(tmp_path, settings)
    item = _item('Black Tea', image_asset=asset)
    token = set_current_company(company)
    try:
        publish.publish_items(company, branches, [item])
    finally:
        reset_current_company(token)
    mi = MenuItem.all_objects.get(company=company)
    assert mi.image_url.endswith('items/kailash/black-tea.webp')
    assert (Path(tmp_path) / 'items' / 'kailash' / 'black-tea.webp').exists()


@pytest.mark.django_db
def test_dietary_tags_carry_over_but_catalog_concepts_do_not(company, branches):
    item = _item('Ruslan Vodka (Qtr.)', base_name='Ruslan Vodka', variant_label='Qtr.',
                 dietary_tags=['veg'], tags=['ruslan', 'vodka'])
    token = set_current_company(company)
    try:
        publish.publish_items(company, branches, [item])
    finally:
        reset_current_company(token)
    mi = MenuItem.all_objects.get(company=company)
    assert mi.name == 'Ruslan Vodka (Qtr.)'      # A/D3 — the name is already complete
    assert mi.dietary_tags == ['veg']
    assert not hasattr(mi, 'variant_label')


@pytest.mark.django_db
def test_two_different_names_that_slugify_alike_stay_separate(company, branches):
    # 'Coke' and 'Coke!' both slugify to 'coke' — the second must not overwrite
    # the first, or a menu silently loses an item.
    items = [_item('Coke'), _item('Coke!')]
    token = set_current_company(company)
    try:
        publish.publish_items(company, branches, items)
    finally:
        reset_current_company(token)
    slugs = set(MenuItem.all_objects.filter(company=company)
                .values_list('slug', flat=True))
    assert len(slugs) == 2


@pytest.mark.django_db
def test_publish_never_reaches_another_tenant(company, branches):
    other = Company.objects.create(name='Chill Zone', slug='chillzone')
    Branch.all_objects.create(company=other, name='Lakeside', slug='lakeside')
    token = set_current_company(company)
    try:
        publish.publish_items(company, branches, [_item('Black Tea')])
    finally:
        reset_current_company(token)
    assert MenuItem.all_objects.filter(company=other).count() == 0
