"""Subcategories survive publishing.

`BranchItemPlacement.sub_category` is a FK to `SubCategory`, not a string --
`PublishRow.sub_category` is a plain name, mirroring how `PublishRow.category`
is a name resolved against `Category` via `ensure_categories`. This file pins
the equivalent resolution for subcategories, done via `ensure_subcategories`.
"""
import pytest

from menu import publish as publish_mod
from menu.models import (Branch, BranchItemPlacement, BranchSubCategory,
                         Company, SubCategory)

pytestmark = pytest.mark.django_db


def _branch():
    company = Company.objects.create(name='Surf and Camp', slug='surfandcamp')
    return company, Branch.all_objects.create(company=company, name='Main',
                                              slug='main')


def test_a_published_row_keeps_its_subcategory():
    company, branch = _branch()
    publish_mod.publish_rows(company, [branch], [
        publish_mod.PublishRow(name='Buff Momo', price=250,
                               category='Nepali Foods', sub_category='Momo'),
    ])
    placed = BranchItemPlacement.objects.get(branch=branch,
                                              menu_item__name='Buff Momo')
    assert placed.category.name == 'Nepali Foods'
    assert placed.sub_category.name == 'Momo'
    assert placed.sub_category.category.name == 'Nepali Foods'


def test_a_row_without_a_subcategory_still_publishes():
    company, branch = _branch()
    publish_mod.publish_rows(company, [branch], [
        publish_mod.PublishRow(name='Veg Soup', price=120, category='Soup'),
    ])
    placed = BranchItemPlacement.objects.get(branch=branch,
                                              menu_item__name='Veg Soup')
    assert placed.category.name == 'Soup'
    assert placed.sub_category is None


def test_the_branch_subcategory_link_is_created():
    company, branch = _branch()
    publish_mod.publish_rows(company, [branch], [
        publish_mod.PublishRow(name='Buff Momo', price=250,
                               category='Nepali Foods', sub_category='Momo'),
    ])
    sub = SubCategory.all_objects.get(company=company, name='Momo')
    assert BranchSubCategory.objects.filter(branch=branch, sub_category=sub).exists()


def test_two_subcategories_under_the_same_category_do_not_collide():
    company, branch = _branch()
    publish_mod.publish_rows(company, [branch], [
        publish_mod.PublishRow(name='Buff Momo', price=250,
                               category='Nepali Foods', sub_category='Momo'),
        publish_mod.PublishRow(name='Chicken Sekuwa', price=300,
                               category='Nepali Foods', sub_category='Sekuwa'),
    ])
    momo = BranchItemPlacement.objects.get(branch=branch,
                                            menu_item__name='Buff Momo')
    sekuwa = BranchItemPlacement.objects.get(branch=branch,
                                              menu_item__name='Chicken Sekuwa')
    assert momo.sub_category.name == 'Momo'
    assert sekuwa.sub_category.name == 'Sekuwa'
    assert momo.sub_category_id != sekuwa.sub_category_id
    assert momo.category_id == sekuwa.category_id
    assert SubCategory.all_objects.filter(company=company,
                                           category=momo.category).count() == 2


def test_differently_cased_category_labels_both_resolve_their_subcategory():
    """Two rows whose `category` text differs only in case/whitespace resolve
    to the SAME `Category` (it's unique on (company, slug), not on name — see
    `ensure_category`). `subs` must therefore be keyed on the resolved
    `Category`'s identity, not on either row's own raw label string, or the
    second row's subcategory silently resolves to None instead of erroring."""
    company, branch = _branch()
    publish_mod.publish_rows(company, [branch], [
        publish_mod.PublishRow(name='Buff Momo', price=250,
                               category='Nepali Foods', sub_category='Momo'),
        publish_mod.PublishRow(name='Chicken Sekuwa', price=300,
                               category=' nepali foods ', sub_category='Sekuwa'),
    ])
    momo = BranchItemPlacement.objects.get(branch=branch,
                                            menu_item__name='Buff Momo')
    sekuwa = BranchItemPlacement.objects.get(branch=branch,
                                              menu_item__name='Chicken Sekuwa')
    # Same underlying Category despite the differing label text.
    assert momo.category_id == sekuwa.category_id
    assert momo.sub_category is not None
    assert sekuwa.sub_category is not None
    assert sekuwa.sub_category.name == 'Sekuwa'


def test_the_branch_subcategory_link_is_created_for_every_branch():
    company = Company.objects.create(name='Two Spot', slug='twospot')
    b1 = Branch.all_objects.create(company=company, name='Lakeside', slug='lakeside')
    b2 = Branch.all_objects.create(company=company, name='Thamel', slug='thamel')
    publish_mod.publish_rows(company, [b1, b2], [
        publish_mod.PublishRow(name='Buff Momo', price=250,
                               category='Nepali Foods', sub_category='Momo'),
    ])
    sub = SubCategory.all_objects.get(company=company, name='Momo')
    for b in (b1, b2):
        assert BranchSubCategory.objects.filter(branch=b, sub_category=sub).exists()
        placed = BranchItemPlacement.objects.get(branch=b, menu_item__name='Buff Momo')
        assert placed.sub_category_id == sub.id
