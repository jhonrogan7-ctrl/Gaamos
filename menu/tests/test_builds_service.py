"""Turning a raw extraction into the wizard's scratch rows."""
import pytest

from menu import builds
from menu.models import (Branch, Company, MenuBuild, MenuBuildRow,
                         MenuBuildSection, MenuScan)


@pytest.fixture
def build(db):
    company = Company.objects.create(name='Kailash Parbat', slug='kailash')
    Branch.all_objects.create(company=company, name='Lakeside', slug='lakeside')
    return MenuBuild.objects.create(company=company)


def _scan(build, items):
    return MenuScan.objects.create(
        file='scans/1.jpg', status='extracted', build=build,
        raw_extraction={'pages': [{'index': 1, 'page_type': 'menu'}], 'items': items})


@pytest.mark.django_db
def test_rows_are_created_under_their_printed_section(build):
    scan = _scan(build, [
        {'name': 'Apple', 'raw_name': 'Apple', 'raw_section': 'JUICE',
         'price': 250, 'source_page': 1},
        {'name': 'Veg Momo', 'raw_name': 'Veg Momo', 'raw_section': 'MOMO',
         'price': 180, 'source_page': 1},
    ])

    written = builds.rows_from_scan(build, scan)

    assert written == 2
    assert set(build.sections.values_list('name', flat=True)) == {'JUICE', 'MOMO'}
    assert build.rows.get(name='Apple').section.name == 'JUICE'


@pytest.mark.django_db
def test_a_row_keeps_the_price_the_card_printed(build):
    """`normalize_item` returns the price under `reference_price` -- reading a
    `price` key that is not there would silently null every price on the card,
    which gate 1 then asks a human to confirm."""
    scan = _scan(build, [{'name': 'Apple', 'raw_name': 'Apple',
                          'raw_section': 'JUICE', 'price': 250, 'source_page': 1}])

    builds.rows_from_scan(build, scan)

    assert build.rows.get(name='Apple').price == 250


@pytest.mark.django_db
def test_a_section_gets_a_suggested_icon_from_its_printed_name(build):
    scan = _scan(build, [{'name': 'Veg Momo', 'raw_name': 'Veg Momo',
                          'raw_section': 'MOMO', 'price': 180, 'source_page': 1}])

    builds.rows_from_scan(build, scan)

    assert build.sections.get(name='MOMO').icon_key


@pytest.mark.django_db
def test_a_row_without_a_printed_section_lands_in_menu(build):
    scan = _scan(build, [{'name': 'Apple', 'raw_name': 'Apple', 'price': 250,
                          'source_page': 1}])

    builds.rows_from_scan(build, scan)

    assert build.rows.get(name='Apple').section.name == 'Menu'


@pytest.mark.django_db
def test_every_row_carries_a_prompt_from_the_start(build):
    """Gate 2 re-rolls from the prompt, so it is composed when the row is born
    rather than derived later from a name that may since have been edited."""
    scan = _scan(build, [{'name': 'Veg Momo', 'raw_name': 'Veg Momo',
                          'raw_section': 'MOMO', 'price': 180, 'source_page': 1}])

    builds.rows_from_scan(build, scan)

    assert build.rows.get(name='Veg Momo').image_prompt


@pytest.mark.django_db
def test_re_extracting_replaces_only_that_scans_rows(build):
    """One bad photograph is re-uploaded on its own. The other four documents'
    rows -- and any correction already typed into them -- must survive."""
    other = MenuScan.objects.create(file='scans/2.jpg', status='extracted', build=build)
    section = MenuBuildSection.objects.create(build=build, name='SNACKS')
    MenuBuildRow.objects.create(build=build, section=section, name='Kept',
                                price=100, source_scan=other)
    scan = _scan(build, [{'name': 'Apple', 'raw_name': 'Apple',
                          'raw_section': 'JUICE', 'price': 250, 'source_page': 1}])
    builds.rows_from_scan(build, scan)

    builds.rows_from_scan(build, scan)

    assert build.rows.filter(source_scan=other).count() == 1
    assert build.rows.filter(source_scan=scan).count() == 1


@pytest.mark.django_db
def test_rows_keep_the_order_the_card_printed_them_in(build):
    scan = _scan(build, [
        {'name': 'First', 'raw_name': 'First', 'raw_section': 'JUICE',
         'price': 100, 'source_page': 1},
        {'name': 'Second', 'raw_name': 'Second', 'raw_section': 'JUICE',
         'price': 110, 'source_page': 1},
    ])

    builds.rows_from_scan(build, scan)

    assert [r.name for r in build.rows.all()] == ['First', 'Second']


@pytest.mark.django_db
def test_section_for_is_idempotent(build):
    a = builds.section_for(build, 'JUICE')
    b = builds.section_for(build, 'JUICE')

    assert a.pk == b.pk
    assert build.sections.count() == 1


@pytest.mark.django_db
def test_an_exact_match_takes_the_library_image(build):
    from menu.models import ImageAsset, Item
    asset = ImageAsset.objects.create(source='flux', status='verified',
                                      file='imagelib/momo.webp')
    Item.objects.create(name='Veg Momo', status='active', search_name='veg momo',
                        category='Momo', image_asset=asset, image_prompt='x')
    section = MenuBuildSection.objects.create(build=build, name='Momo')
    MenuBuildRow.objects.create(build=build, section=section, name='Veg Momo', price=180)

    counts = builds.match_build_rows(build, embedder=None)

    row = build.rows.get(name='Veg Momo')
    assert counts['auto'] == 1
    assert row.match_state == 'auto'
    assert row.image_state == 'matched'
    assert row.image_asset_id == asset.pk


@pytest.mark.django_db
def test_a_row_with_no_counterpart_stays_imageless(build):
    section = MenuBuildSection.objects.create(build=build, name='Momo')
    MenuBuildRow.objects.create(build=build, section=section, name='Veg Momo', price=180)

    counts = builds.match_build_rows(build, embedder=None)

    row = build.rows.get(name='Veg Momo')
    assert counts['none'] == 1
    assert row.match_state == 'none'
    assert row.image_state == 'none'
    assert row.image_asset_id is None


@pytest.mark.django_db
def test_a_suggested_match_records_its_candidate_but_takes_no_image(build):
    """Founder ruling: a fuzzy match may suggest, never auto-apply. Gate 2 does
    not exist in 4a, so the row publishes imageless -- but the candidate is kept
    so 4b can offer it without re-running the matcher."""
    from django.test import override_settings
    from menu.models import ImageAsset, Item
    asset = ImageAsset.objects.create(source='flux', status='verified',
                                      file='imagelib/x.webp')
    Item.objects.create(name='Masala Chowmein', status='active',
                        search_name='masala chowmein', category='Chowmein',
                        image_asset=asset, image_prompt='x')
    section = MenuBuildSection.objects.create(build=build, name='Chowmein')
    MenuBuildRow.objects.create(build=build, section=section,
                                name='Masaala Chowmein', price=250)

    with override_settings(MENU_MATCH_HIGH=0.90, MENU_MATCH_MID=0.55):
        counts = builds.match_build_rows(build, embedder=None)

    row = build.rows.get(name='Masaala Chowmein')
    assert counts['suggested'] == 1
    assert row.match_state == 'suggested'
    assert row.matched_item is not None
    assert row.image_state == 'none'
    assert row.image_asset_id is None


@pytest.mark.django_db
def test_matching_passes_the_section_so_a_bare_name_is_identified(build):
    """`Apple` under JUICE is a different dish from `Apple` under MILK SHAKE.
    The matcher can only know that if the section reaches it."""
    from menu.models import Item
    Item.objects.create(name='Apple', status='active', search_name='apple juice',
                        category='Juice', image_prompt='x')
    section = MenuBuildSection.objects.create(build=build, name='Juice')
    MenuBuildRow.objects.create(build=build, section=section, name='Apple', price=250)

    counts = builds.match_build_rows(build, embedder=None)

    assert counts['auto'] == 1


@pytest.mark.django_db
def test_publishing_writes_the_printed_price_to_the_tenant(build):
    from menu.models import MenuItem
    branch = Branch.all_objects.get(company=build.company)
    build.branches.add(branch)
    section = MenuBuildSection.objects.create(build=build, name='Hot Drinks')
    MenuBuildRow.objects.create(build=build, section=section, name='Black Tea', price=60)

    builds.publish_build(build)

    assert MenuItem.all_objects.get(company=build.company, name='Black Tea').price == 60
    assert build.status == 'published'


@pytest.mark.django_db
def test_publishing_links_each_row_to_the_item_it_created(build):
    branch = Branch.all_objects.get(company=build.company)
    build.branches.add(branch)
    section = MenuBuildSection.objects.create(build=build, name='Hot Drinks')
    MenuBuildRow.objects.create(build=build, section=section, name='Black Tea', price=60)

    builds.publish_build(build)

    assert build.rows.get(name='Black Tea').published_item is not None


@pytest.mark.django_db
def test_an_unmatched_row_becomes_a_new_library_entry(build):
    from menu.models import Item
    branch = Branch.all_objects.get(company=build.company)
    build.branches.add(branch)
    section = MenuBuildSection.objects.create(build=build, name='Hot Drinks')
    MenuBuildRow.objects.create(build=build, section=section, name='Sherpa Punch',
                                price=340, image_prompt='a punch')

    report = builds.publish_build(build)

    entry = Item.objects.get(name='Sherpa Punch', status='active')
    assert entry.origin_company_id == build.company_id
    assert entry.search_name
    assert entry.image_prompt == 'a punch'
    assert report.library_created == 1


@pytest.mark.django_db
def test_a_matched_row_bumps_the_entry_usage_instead_of_duplicating_it(build):
    from menu.models import Item
    branch = Branch.all_objects.get(company=build.company)
    build.branches.add(branch)
    entry = Item.objects.create(name='Black Tea', status='active',
                                search_name='black tea', category='Hot Drinks',
                                image_prompt='x', use_count=1)
    section = MenuBuildSection.objects.create(build=build, name='Hot Drinks')
    MenuBuildRow.objects.create(build=build, section=section, name='Black Tea',
                                price=60, matched_item=entry, match_state='auto')

    report = builds.publish_build(build)

    entry.refresh_from_db()
    assert entry.use_count == 2
    assert report.library_reused == 1
    assert Item.objects.filter(search_name='black tea', status='active').count() == 1


@pytest.mark.django_db
def test_usage_from_the_backfill_survives_a_build_publishing_the_entry(build):
    """`use_count` is incremented, never recomputed from build rows. Phase 1's
    backfill counted venues that never went through a build, and a recompute
    would erase all of them the first time one venue was onboarded."""
    from menu.models import Item
    build.branches.add(Branch.all_objects.get(company=build.company))
    entry = Item.objects.create(name='Black Tea', status='active',
                                search_name='black tea', category='Hot Drinks',
                                image_prompt='x', use_count=9)
    section = MenuBuildSection.objects.create(build=build, name='Hot Drinks')
    MenuBuildRow.objects.create(build=build, section=section, name='Black Tea',
                                price=60, matched_item=entry, match_state='auto')

    builds.publish_build(build)

    entry.refresh_from_db()
    assert entry.use_count == 10


@pytest.mark.django_db
def test_one_venue_printing_a_dish_in_two_sections_counts_once(build):
    from menu.models import Item
    build.branches.add(Branch.all_objects.get(company=build.company))
    entry = Item.objects.create(name='Black Tea', status='active',
                                search_name='black tea', category='Hot Drinks',
                                image_prompt='x', use_count=1)
    for name in ('Hot Drinks', 'Breakfast'):
        section = MenuBuildSection.objects.create(build=build, name=name)
        MenuBuildRow.objects.create(build=build, section=section, name='Black Tea',
                                    price=60, matched_item=entry, match_state='auto')

    builds.publish_build(build)

    entry.refresh_from_db()
    assert entry.use_count == 2


@pytest.mark.django_db
def test_publishing_twice_does_not_duplicate_the_menu_or_the_usage(build):
    from menu.models import Item, MenuItem
    branch = Branch.all_objects.get(company=build.company)
    build.branches.add(branch)
    section = MenuBuildSection.objects.create(build=build, name='Hot Drinks')
    MenuBuildRow.objects.create(build=build, section=section, name='Black Tea',
                                price=60, image_prompt='x')

    builds.publish_build(build)
    builds.publish_build(build)

    assert MenuItem.all_objects.filter(company=build.company).count() == 1
    assert Item.objects.filter(search_name='black tea', status='active').count() == 1
    # The whole "publish now, add images in 4b" story rests on this.
    assert Item.objects.get(search_name='black tea').use_count == 1


@pytest.mark.django_db
def test_a_section_icon_reaches_the_published_category(build):
    from menu.models import Category
    branch = Branch.all_objects.get(company=build.company)
    build.branches.add(branch)
    section = MenuBuildSection.objects.create(build=build, name='Momo', icon_key='momo')
    MenuBuildRow.objects.create(build=build, section=section, name='Veg Momo', price=180)

    builds.publish_build(build)

    assert Category.all_objects.get(company=build.company, name='Momo').icon_key == 'momo'
