import pytest
from django.db import IntegrityError, transaction

from menu.models import Company, MenuBuild, MenuBuildRow, MenuBuildSection

pytestmark = pytest.mark.django_db


def _build():
    company = Company.objects.create(name='Surf and Camp', slug='surfandcamp')
    return MenuBuild.objects.create(company=company, status='draft')


def test_a_section_carries_its_subcategory():
    build = _build()
    section = MenuBuildSection.objects.create(
        build=build, name='Nepali Foods', sub_name='Momo', display_order=0)
    assert section.sub_name == 'Momo'


def test_the_same_category_may_hold_several_subcategories():
    build = _build()
    for order, sub in enumerate(['Momo', 'Noodles', 'Platter']):
        MenuBuildSection.objects.create(build=build, name='Nepali Foods',
                                        sub_name=sub, display_order=order)
    assert build.sections.filter(name='Nepali Foods').count() == 3


def test_the_same_pair_cannot_repeat():
    build = _build()
    MenuBuildSection.objects.create(build=build, name='Nepali Foods',
                                    sub_name='Momo', display_order=0)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            MenuBuildSection.objects.create(build=build, name='Nepali Foods',
                                            sub_name='Momo', display_order=1)


def test_a_row_keeps_the_sheet_note():
    build = _build()
    section = MenuBuildSection.objects.create(build=build, name='Soup',
                                              display_order=0)
    row = MenuBuildRow.objects.create(
        build=build, section=section, display_order=0, name='Veg Soup',
        price=120, notes='Price unclear (inferred)')
    assert row.notes == 'Price unclear (inferred)'


def test_needs_check_is_derived_from_the_note():
    build = _build()
    section = MenuBuildSection.objects.create(build=build, name='Soup',
                                              display_order=0)
    quiet = MenuBuildRow.objects.create(build=build, section=section,
                                        display_order=0, name='A', price=100)
    loud = MenuBuildRow.objects.create(build=build, section=section,
                                       display_order=1, name='B', price=100,
                                       notes='Duplicate of row 4')
    assert quiet.needs_check is False
    assert loud.needs_check is True
