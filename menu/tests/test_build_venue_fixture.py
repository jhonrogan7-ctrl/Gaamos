"""The sheet is the source of truth: sections become categories, rows become
items, and the join key the fixture writes must equal the key the generator
used when it named the image."""
from menu.management.commands.build_venue_fixture import build_catalog
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
