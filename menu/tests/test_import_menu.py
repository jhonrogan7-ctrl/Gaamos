import json
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from menu.models import Company, Branch
from menu.tenancy import set_current_company, reset_current_company


@pytest.fixture
def company(db):
    c = Company.objects.create(name="Tranquility Inn", slug="tranquility-inn")
    Branch.all_objects.create(company=c, slug="restaurant", name="Restaurant", address="")
    token = set_current_company(c)
    yield c
    reset_current_company(token)


def _write_fixture(tmp_path, data):
    p = tmp_path / "fix.json"
    p.write_text(json.dumps(data))
    return str(p)


def test_missing_company_is_hard_error(db, tmp_path):
    fixture = _write_fixture(tmp_path, {"company": "ghost", "categories": [], "items": []})
    with pytest.raises(CommandError, match="No company with slug 'ghost'"):
        call_command("import_menu", "--company", "ghost", "--fixture", fixture)


def test_unknown_branch_is_hard_error(company, tmp_path):
    fixture = _write_fixture(tmp_path, {"company": "tranquility-inn", "categories": [], "items": []})
    with pytest.raises(CommandError, match="Branch 'spa' not found"):
        call_command("import_menu", "--company", "tranquility-inn",
                     "--branch", "spa", "--fixture", fixture)


def test_dry_run_writes_nothing(company, tmp_path):
    fixture = _write_fixture(tmp_path, {
        "company": "tranquility-inn",
        "categories": [{"slug": "starters", "name": "Starters", "display_order": 1,
                        "icon_key": "", "hours_note": "", "subcategories": []}],
        "items": []})
    call_command("import_menu", "--company", "tranquility-inn",
                 "--fixture", fixture, "--dry-run")
    from menu.models import Category
    assert Category.all_objects.filter(company=company).count() == 0


def test_categories_and_subs_upsert_idempotently(company, tmp_path):
    data = {"company": "tranquility-inn",
            "categories": [{"slug": "starters", "name": "Starters", "display_order": 2,
                            "icon_key": "star", "hours_note": "",
                            "subcategories": [{"name": "Soups", "icon_key": "subAll",
                                               "display_order": 1}]}],
            "items": []}
    fixture = _write_fixture(tmp_path, data)
    from menu.models import Category, SubCategory
    call_command("import_menu", "--company", "tranquility-inn", "--fixture", fixture)
    assert Category.all_objects.filter(company=company).count() == 1
    cat = Category.all_objects.get(company=company, slug="starters")
    assert cat.name == "Starters" and cat.display_order == 2
    assert SubCategory.all_objects.filter(company=company, category=cat).count() == 1
    # Re-run: no duplicates, updated fields
    data["categories"][0]["name"] = "Small Plates"
    call_command("import_menu", "--company", "tranquility-inn",
                 "--fixture", _write_fixture(tmp_path, data))
    assert Category.all_objects.filter(company=company).count() == 1
    assert SubCategory.all_objects.filter(company=company).count() == 1
    assert Category.all_objects.get(company=company, slug="starters").name == "Small Plates"


def test_items_upsert_with_fields(company, tmp_path):
    data = {"company": "tranquility-inn",
            "categories": [{"slug": "starters", "name": "Starters", "display_order": 1,
                            "icon_key": "", "hours_note": "",
                            "subcategories": [{"name": "Soups", "icon_key": "subAll",
                                               "display_order": 1}]}],
            "items": [{"slug": "boiled-egg", "name": "Boiled Egg", "cat": "starters",
                       "sub": "Soups", "description": "Farm egg.", "price": 120,
                       "tags": ["veg"], "popular": True, "featured": False,
                       "order": 1, "image": None}]}
    fixture = _write_fixture(tmp_path, data)
    from menu.models import MenuItem
    call_command("import_menu", "--company", "tranquility-inn", "--fixture", fixture)
    item = MenuItem.all_objects.get(company=company, slug="boiled-egg")
    assert item.price == 120 and item.is_popular is True
    assert item.dietary_tags == ["veg"] and item.description == "Farm egg."
    # Re-run with a price change → updates, no duplicate
    data["items"][0]["price"] = 150
    call_command("import_menu", "--company", "tranquility-inn",
                 "--fixture", _write_fixture(tmp_path, data))
    assert MenuItem.all_objects.filter(company=company).count() == 1
    assert MenuItem.all_objects.get(company=company, slug="boiled-egg").price == 150


def test_items_attached_only_to_named_branch(company, tmp_path):
    from menu.models import Branch, BranchMenuItem, BranchItemPlacement, MenuItem
    Branch.all_objects.create(company=company, slug="rooftop", name="Rooftop", address="")
    data = {"company": "tranquility-inn",
            "categories": [{"slug": "starters", "name": "Starters", "display_order": 1,
                            "icon_key": "", "hours_note": "", "subcategories": []}],
            "items": [{"slug": "boiled-egg", "name": "Boiled Egg", "cat": "starters",
                       "sub": None, "description": "", "price": 120, "tags": [],
                       "popular": False, "featured": False, "order": 3, "image": None}]}
    call_command("import_menu", "--company", "tranquility-inn", "--branch", "restaurant",
                 "--fixture", _write_fixture(tmp_path, data))
    item = MenuItem.all_objects.get(company=company, slug="boiled-egg")
    linked = {bmi.branch.slug for bmi in BranchMenuItem.objects.filter(menu_item=item)}
    assert linked == {"restaurant"}                 # not rooftop
    pl = BranchItemPlacement.objects.get(menu_item=item, branch__slug="restaurant")
    assert pl.category.slug == "starters" and pl.sub_category is None
    assert pl.display_order == 3
    # Idempotent re-run
    call_command("import_menu", "--company", "tranquility-inn", "--branch", "restaurant",
                 "--fixture", _write_fixture(tmp_path, data))
    assert BranchItemPlacement.objects.filter(menu_item=item).count() == 1


def _make_webp(path):
    from PIL import Image
    Image.new("RGB", (40, 30), (200, 30, 30)).save(path, "WEBP")


def test_image_downloaded_and_saved_under_company_path(company, tmp_path, settings):
    src = tmp_path / "src"; src.mkdir()
    _make_webp(src / "boiled-egg.webp")
    data = {"company": "tranquility-inn",
            "categories": [{"slug": "starters", "name": "Starters", "display_order": 1,
                            "icon_key": "", "hours_note": "", "subcategories": []}],
            "items": [{"slug": "boiled-egg", "name": "Boiled Egg", "cat": "starters",
                       "sub": None, "description": "", "price": 120, "tags": [],
                       "popular": False, "featured": False, "order": 1,
                       "image": {"file": "boiled-egg.webp", "source": "found",
                                 "origin_url": "https://x/y.jpg", "prompt": None}}]}
    call_command("import_menu", "--company", "tranquility-inn",
                 "--media-base", src.as_uri(),
                 "--fixture", _write_fixture(tmp_path, data))
    from menu.models import MenuItem
    item = MenuItem.all_objects.get(company=company, slug="boiled-egg")
    assert item.image_url == "/media/items/tranquility-inn/boiled-egg.webp"
    saved = Path(settings.MEDIA_ROOT) / "items" / "tranquility-inn" / "boiled-egg.webp"
    assert saved.exists()


def test_missing_image_nonstrict_imports_imageless(company, tmp_path):
    data = {"company": "tranquility-inn",
            "categories": [{"slug": "starters", "name": "Starters", "display_order": 1,
                            "icon_key": "", "hours_note": "", "subcategories": []}],
            "items": [{"slug": "ghost-dish", "name": "Ghost", "cat": "starters", "sub": None,
                       "description": "", "price": 10, "tags": [], "popular": False,
                       "featured": False, "order": 1,
                       "image": {"file": "nope.webp", "source": "found",
                                 "origin_url": None, "prompt": None}}]}
    call_command("import_menu", "--company", "tranquility-inn",
                 "--media-base", (tmp_path / "empty").as_uri(),
                 "--fixture", _write_fixture(tmp_path, data))
    from menu.models import MenuItem
    assert MenuItem.all_objects.get(company=company, slug="ghost-dish").image_url == ""


def test_missing_image_strict_aborts(company, tmp_path):
    data = {"company": "tranquility-inn", "categories": [], "items": [
        {"slug": "ghost", "name": "Ghost", "cat": None, "sub": None, "description": "",
         "price": 10, "tags": [], "popular": False, "featured": False, "order": 1,
         "image": {"file": "nope.webp", "source": "found", "origin_url": None, "prompt": None}}]}
    with pytest.raises(CommandError, match="image download failed"):
        call_command("import_menu", "--company", "tranquility-inn", "--strict",
                     "--media-base", (tmp_path / "empty").as_uri(),
                     "--fixture", _write_fixture(tmp_path, data))
