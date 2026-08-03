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
