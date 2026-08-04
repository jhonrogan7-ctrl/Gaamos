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
def test_a_section_subcategory_reaches_the_published_placement(build):
    """The plan's File Structure line for this module reads: add
    `rows_from_sheet`, pass `sub_category` at publish. A section's `sub_name`
    (Task 2) must reach the guest menu, or subcategories never survive
    publishing (Task 3's whole point)."""
    from menu.models import BranchItemPlacement, SubCategory
    branch = Branch.all_objects.get(company=build.company)
    build.branches.add(branch)
    section = MenuBuildSection.objects.create(build=build, name='Nepali Foods',
                                              sub_name='Momo')
    MenuBuildRow.objects.create(build=build, section=section, name='Veg Momo', price=180)

    builds.publish_build(build)

    placement = BranchItemPlacement.objects.get(branch=branch, menu_item__name='Veg Momo')
    assert placement.sub_category == SubCategory.all_objects.get(company=build.company, name='Momo')


@pytest.mark.django_db
def test_a_section_icon_reaches_the_published_category(build):
    from menu.models import Category
    branch = Branch.all_objects.get(company=build.company)
    build.branches.add(branch)
    section = MenuBuildSection.objects.create(build=build, name='Momo', icon_key='momo')
    MenuBuildRow.objects.create(build=build, section=section, name='Veg Momo', price=180)

    builds.publish_build(build)

    assert Category.all_objects.get(company=build.company, name='Momo').icon_key == 'momo'
