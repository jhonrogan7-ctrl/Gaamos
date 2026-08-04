import pytest

from menu import builds as build_service
from menu.models import Company, MenuBuild
from menu.pipeline.xlsx_import import SheetRow

pytestmark = pytest.mark.django_db


def _build():
    company = Company.objects.create(name='Surf and Camp', slug='surfandcamp')
    return MenuBuild.objects.create(company=company, status='draft')


def _row(**kw):
    base = dict(line=2, category='Veg Snacks', sub_category='', item='French Fries',
                variant='Plain', description='', price=250,
                subject='golden crispy french fries', notes='')
    base.update(kw)
    return SheetRow(**base)


def test_writes_one_row_per_sheet_row():
    build = _build()
    written = build_service.rows_from_sheet(build, [_row(), _row(
        line=3, variant='Chilli', price=280,
        subject='spicy chilli french fries')])
    assert written == 2
    assert build.rows.count() == 2


def test_a_category_and_subcategory_make_one_section():
    build = _build()
    build_service.rows_from_sheet(build, [
        _row(category='Nepali Foods', sub_category='Momo', item='Buff Momo',
             subject='steamed buff momo dumplings'),
        _row(line=3, category='Nepali Foods', sub_category='Noodles',
             item='Veg Chowmein', subject='vegetable chowmein noodles'),
        _row(line=4, category='Nepali Foods', sub_category='Momo',
             item='Veg Momo', subject='steamed vegetable momo dumplings'),
    ])
    sections = build.sections.filter(name='Nepali Foods')
    assert sections.count() == 2
    assert set(sections.values_list('sub_name', flat=True)) == {'Momo', 'Noodles'}


def test_the_sheet_fields_land_on_the_row():
    build = _build()
    build_service.rows_from_sheet(build, [_row(
        description='Hand-cut potatoes', notes='Price unclear (inferred)')])
    row = build.rows.get()
    assert row.name == 'French Fries'
    assert row.variant_label == 'Plain'
    assert row.description == 'Hand-cut potatoes'
    assert row.price == 250
    assert row.notes == 'Price unclear (inferred)'
    assert row.needs_check is True


def test_the_prompt_is_composed_from_the_subject_not_the_name():
    build = _build()
    build_service.rows_from_sheet(build, [_row(
        subject='golden crispy french fries')])
    prompt = build.rows.get().image_prompt
    assert 'golden crispy french fries' in prompt
    # The shared style block is appended by the platform, never by the sheet.
    assert 'no garnish' in prompt


def test_a_drink_section_gets_the_drink_style_block():
    # NOTE: brief specified category='Beverages & Others', but prompts.is_drink
    # (must not change -- see prompts_golden fixture) only matches _DRINK_WORDS
    # ('drink', 'juice', 'lassi', ...) or the exact sections {'rum', 'gin'};
    # "beverage" is not one of them, so that category never triggers the drink
    # style block. Swapped to 'Hot Drinks', which does, matching the section
    # name already used for Black Tea in test_builds_service.py.
    build = _build()
    build_service.rows_from_sheet(build, [_row(
        category='Hot Drinks', item='Black Tea', variant='',
        subject='a glass of black tea')])
    assert 'beverage photography' in build.rows.get().image_prompt


def test_rewriting_a_build_replaces_its_rows():
    build = _build()
    build_service.rows_from_sheet(build, [_row()])
    build_service.rows_from_sheet(build, [_row(item='Papad',
                                               subject='crisp papad')])
    assert build.rows.count() == 1
    assert build.rows.get().name == 'Papad'


def test_display_order_follows_the_sheet():
    build = _build()
    build_service.rows_from_sheet(build, [
        _row(item='A', subject='dish a'),
        _row(line=3, item='B', subject='dish b'),
        _row(line=4, item='C', subject='dish c'),
    ])
    ordered = list(build.rows.order_by('display_order')
                   .values_list('name', flat=True))
    assert ordered == ['A', 'B', 'C']
