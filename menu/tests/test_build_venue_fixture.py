"""The sheet is the source of truth: sections become categories, rows become
items, and the join key the fixture writes must equal the key the generator
used when it named the image."""
import io
import json

import pytest
from django.core.management import CommandError, call_command
from PIL import Image

from menu.management.commands.build_venue_fixture import build_catalog
from menu.models import ImageAsset
from menu.pipeline import prompt_sheet

SHEET = """## Venue

| Field | Value |
|---|---|
| slug | chillzone |
| name | Chill Zone |
| branch.main.name | Chill Zone |

## Card 1

### Hot Drinks

| Item | Description | Price | Image prompt |
|---|---|---|---|
| Black Tea | Strong black tea. | 40 | a glass of black tea |
| Extra Cup | — | | *skip — accessory* |

### Milk Shake

| Item | Description | Price | Image prompt |
|---|---|---|---|
| Banana | Thick banana shake. | 180 | a tall glass of banana milkshake |

### Pancakes

| Item | Description | Price | Image prompt |
|---|---|---|---|
| Banana | Banana pancake stack. | 220 | a stack of banana pancakes |
"""


def _built():
    return build_catalog(prompt_sheet.parse(SHEET))


def test_sections_become_categories_in_appearance_order():
    categories, _, _ = _built()

    assert [c["slug"] for c in categories] == ["hot-drinks", "milk-shake", "pancakes"]
    assert [c["name"] for c in categories] == ["Hot Drinks", "Milk Shake", "Pancakes"]
    assert [c["display_order"] for c in categories] == [1, 2, 3]


def test_a_category_carries_the_keys_import_menu_reads():
    categories, _, _ = _built()

    assert categories[0]["icon_key"] == "" and categories[0]["hours_note"] == ""
    assert categories[0]["subcategories"] == []


def test_items_carry_name_description_price_and_category():
    _, items, _ = _built()

    tea = next(i for i in items if i["name"] == "Black Tea")
    assert tea["cat"] == "hot-drinks"
    assert tea["description"] == "Strong black tea."
    assert tea["price"] == 40
    assert tea["sub"] is None and tea["tags"] == []
    assert tea["popular"] is False and tea["featured"] is False


def test_a_row_with_no_price_is_reported_not_imported():
    _, items, unpriced = _built()

    assert "Extra Cup" not in [i["name"] for i in items]
    assert unpriced == ["hot-drinks-extra-cup"]


def test_a_repeated_item_name_gets_a_unique_item_slug():
    """`import_menu` upserts on (company, item slug) — two `banana` rows would
    collapse into one menu item, and the second price would win."""
    _, items, _ = _built()

    slugs = [i["slug"] for i in items if i["name"] == "Banana"]
    assert slugs == ["banana", "banana-pancakes"]
    assert len({i["slug"] for i in items}) == len(items)


def test_the_join_key_stays_the_sheet_key_even_when_the_slug_moved():
    """Uniquifying the item slug must not break the exact-match pass."""
    _, items, _ = _built()

    banana_pancake = next(i for i in items if i["slug"] == "banana-pancakes")
    assert banana_pancake["key"] == "pancakes-banana"


def test_display_order_restarts_within_each_category():
    _, items, _ = _built()

    assert next(i for i in items if i["slug"] == "black-tea")["order"] == 1
    assert next(i for i in items if i["slug"] == "banana")["order"] == 1


# --- the review gate: --require-verified ------------------------------------

def _webp_asset(key, media_root, status, *, prompt="", tag=""):
    rel = f"imagelib/{key}{tag}.webp"
    dest = media_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (10, 20, 30)).save(buf, "WEBP")
    dest.write_bytes(buf.getvalue())
    return ImageAsset.objects.create(source="flux", file=rel, status=status,
                                     found_for_slug=key, content_hash=key + tag,
                                     name=key, prompt=prompt)


@pytest.fixture
def built_sheet(tmp_path):
    path = tmp_path / "sheet.md"
    path.write_text(SHEET)
    return str(path)


def _build(built_sheet, tmp_path, *extra):
    call_command("build_venue_fixture", "--prompts", built_sheet,
                 "--company", "chillzone", *extra,
                 "--out", str(tmp_path / "out.json"),
                 "--media-out", str(tmp_path / "mediaout"))


@pytest.mark.django_db
def test_require_verified_refuses_a_pending_asset_and_names_its_key(
        built_sheet, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    _webp_asset("hot-drinks-black-tea", tmp_path / "media", "pending")

    with pytest.raises(CommandError) as exc:
        _build(built_sheet, tmp_path, "--require-verified")

    assert "hot-drinks-black-tea" in str(exc.value)


@pytest.mark.django_db
def test_require_verified_passes_when_every_chosen_asset_is_verified(
        built_sheet, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    _webp_asset("hot-drinks-black-tea", tmp_path / "media", "verified")

    _build(built_sheet, tmp_path, "--require-verified")

    assert (tmp_path / "out.json").exists()


@pytest.mark.django_db
def test_without_the_flag_a_pending_asset_still_builds(built_sheet, settings,
                                                       tmp_path):
    """Opt-in for now: Tranquility's set is unreviewed and must stay buildable."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    _webp_asset("hot-drinks-black-tea", tmp_path / "media", "pending")

    _build(built_sheet, tmp_path)

    assert (tmp_path / "out.json").exists()


@pytest.mark.django_db
def test_a_rerolled_key_ships_the_new_image_not_the_rejected_one(
        built_sheet, settings, tmp_path):
    """A re-roll ADDS a row (new content hash) and leaves the rejected one in
    place, so both share `found_for_slug`. Default ordering is `-created_at`,
    which made the oldest — the rejected image — win the lookup."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    _webp_asset("hot-drinks-black-tea", tmp_path / "media", "rejected",
                prompt="the rejected image", tag="-old")
    _webp_asset("hot-drinks-black-tea", tmp_path / "media", "verified",
                prompt="the re-rolled image", tag="-new")

    _build(built_sheet, tmp_path, "--require-verified")

    fixture = json.loads((tmp_path / "out.json").read_text())
    black_tea = next(i for i in fixture["items"] if i["slug"] == "black-tea")
    assert black_tea["image"]["prompt"] == "the re-rolled image"


@pytest.mark.django_db
def test_require_verified_names_a_key_whose_only_asset_is_rejected(
        built_sheet, settings, tmp_path):
    """Rejected assets are excluded from selection, so such a key would
    otherwise ship imageless and silently."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    _webp_asset("hot-drinks-black-tea", tmp_path / "media", "rejected")

    with pytest.raises(CommandError) as exc:
        _build(built_sheet, tmp_path, "--require-verified")

    assert "hot-drinks-black-tea" in str(exc.value)
