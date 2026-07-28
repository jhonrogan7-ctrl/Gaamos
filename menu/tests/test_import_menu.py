import json
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from menu import publish
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


def _png_bytes():
    from io import BytesIO

    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (12, 12), "red").save(buf, format="PNG")
    return buf.getvalue()


def test_media_base_can_be_a_local_directory(company, tmp_path, settings):
    """Fixture media are already on disk — serving them over HTTP first was
    ceremony, and a stale dev server serving an old file was a real failure."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    media_dir = tmp_path / "fixture-media"
    media_dir.mkdir()
    (media_dir / "starters-momo.webp").write_bytes(_png_bytes())
    data = {"categories": [{"slug": "starters", "name": "Starters",
                            "display_order": 1, "icon_key": "", "hours_note": "",
                            "subcategories": []}],
            "items": [{"slug": "momo", "name": "Momo", "cat": "starters",
                       "sub": None, "description": "", "price": 200, "tags": [],
                       "popular": False, "featured": False, "order": 1,
                       "image": {"file": "starters-momo.webp",
                                 "source": "generated", "origin_url": None,
                                 "prompt": None}}]}

    call_command("import_menu", "--company", "tranquility-inn",
                 "--fixture", _write_fixture(tmp_path, data),
                 "--media-base", str(media_dir), "--strict")

    from menu.models import MenuItem
    item = MenuItem.all_objects.get(company=company, slug="momo")
    assert item.image_url.endswith("items/tranquility-inn/momo.webp")


def test_a_missing_local_media_file_is_reported_like_a_failed_download(
        company, tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    media_dir = tmp_path / "empty"
    media_dir.mkdir()
    data = {"categories": [],
            "items": [{"slug": "momo", "name": "Momo", "cat": None, "sub": None,
                       "description": "", "price": 200, "tags": [],
                       "popular": False, "featured": False, "order": 1,
                       "image": {"file": "gone.webp", "source": "generated",
                                 "origin_url": None, "prompt": None}}]}

    with pytest.raises(CommandError, match="image download failed for momo"):
        call_command("import_menu", "--company", "tranquility-inn",
                     "--fixture", _write_fixture(tmp_path, data),
                     "--media-base", str(media_dir), "--strict")


def _cat(company, icon_key, *, slug='momo', update=True):
    cat, created = publish.ensure_category(
        company, [], name='Momo', slug=slug, icon_key=icon_key, update=update)
    return cat, created


def test_a_blank_icon_key_does_not_clear_an_existing_one(company):
    """A venue's own icon, chosen in the dashboard, must survive a re-import of
    a fixture that has no opinion about icons.

    Every fixture generated before category_icons existed carries
    `icon_key: ""`, and re-importing a live venue is routine — adding a second
    card to a tenant does exactly that.
    """
    _cat(company, 'momo')
    cat, _ = _cat(company, '')
    assert cat.icon_key == 'momo'


def test_a_real_icon_key_still_overwrites(company):
    """The fixture stays authoritative about anything it actually states."""
    _cat(company, 'momo')
    cat, _ = _cat(company, 'thali')
    assert cat.icon_key == 'thali'


def test_a_new_category_still_receives_a_blank(company):
    cat, created = _cat(company, '', slug='soups')
    assert created and cat.icon_key == ''


def test_the_no_update_path_is_unaffected(company):
    _cat(company, 'momo')
    cat, created = _cat(company, 'thali', update=False)
    assert not created and cat.icon_key == 'momo'
