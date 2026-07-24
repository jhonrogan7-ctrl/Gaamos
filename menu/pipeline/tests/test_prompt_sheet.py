"""The prompt sheet is a hand-written markdown worksheet (vault:
menius/<venue>/…-items-and-image-prompts.md), not a generated file — so the
parser has to tolerate the things a human does to a markdown table."""
from menu.pipeline import prompt_sheet

SHEET = """# Venue — Item List + Image Generation Prompts

Some preamble prose.

**Style block — append to every food prompt:**

```
, professional food photography
```

## How to use these prompts

**Suggested settings**

| Setting | Value | Why |
|---|---|---|
| Model | **Seedream V5 pro** | Strongest photoreal food rendering |
| Aspect ratio | **1:1** | Guest menu renders square cards |

## Card 1 — Hot Drinks, Breakfast

### Hot Drinks

| Item | Printed description | Image prompt |
|---|---|---|
| Black Tea | — | a clear glass cup of strong black tea, no milk |
| Milk Tea | — | a glass cup of Nepali milk tea |

### Breakfast

| Item                | Printed description             | Image prompt                        |
| ------------------- | ------------------------------- | ----------------------------------- |
| Simple Breakfast    | Two egg any style, toast.       | a breakfast plate with two eggs      |

## Card 2 — Hukka, Hard Drinks

### Hukka

| Item | Printed description | Image prompt |
|---|---|---|
| Mint, Double Apple | — | an ornate blue glass shisha hookah pipe |
| Extra Coil | — | *skip — accessory, no image needed* |

> A blockquote note that must not be parsed as a row.

### Hard Drinks

Sold in **60ml / Quarter** measures.

*Prose between the heading and the table.*

| Item | Spirit type | Image prompt (shared per type) |
|---|---|---|
| Ruslan Vodka | Vodka | a chilled shot of clear vodka |
| 8848 Vodka | Vodka | *(reuse the vodka image)* |
"""


def _by_item(rows):
    return {r["item"]: r for r in rows}


def test_parses_item_description_and_prompt_from_a_table_row():
    rows = prompt_sheet.parse(SHEET)

    tea = _by_item(rows)["Black Tea"]
    assert tea["prompt"] == "a clear glass cup of strong black tea, no milk"
    assert tea["description"] == ""          # the em dash means "none printed"


def test_keeps_the_printed_description_when_there_is_one():
    rows = prompt_sheet.parse(SHEET)

    assert _by_item(rows)["Simple Breakfast"]["description"] == \
        "Two egg any style, toast."


def test_tracks_the_card_and_section_each_row_came_from():
    rows = prompt_sheet.parse(SHEET)

    tea = _by_item(rows)["Black Tea"]
    assert tea["section"] == "Hot Drinks"
    assert tea["card"] == "Card 1 — Hot Drinks, Breakfast"


def test_tolerates_padded_column_widths():
    """The Breakfast table is space-padded; the Hot Drinks one is not."""
    rows = prompt_sheet.parse(SHEET)

    assert _by_item(rows)["Simple Breakfast"]["prompt"] == \
        "a breakfast plate with two eggs"


def test_italic_directive_rows_are_parsed_but_not_generatable():
    """`*skip — …*` and `*(reuse the vodka image)*` are instructions to a human,
    not prompts. They stay in the parse (the sheet is the item list) but must
    never be sent to an image model."""
    rows = _by_item(prompt_sheet.parse(SHEET))

    assert rows["Extra Coil"]["generatable"] is False
    assert rows["8848 Vodka"]["generatable"] is False
    assert rows["Mint, Double Apple"]["generatable"] is True
    assert rows["Ruslan Vodka"]["generatable"] is True


def test_second_column_is_only_a_description_when_the_header_says_so():
    """The Hard Drinks table's middle column is `Spirit type` — 'Vodka' is not
    a printed menu description and must not be stored as one."""
    rows = prompt_sheet.parse(SHEET)

    assert _by_item(rows)["Ruslan Vodka"]["description"] == ""


def test_keeps_the_raw_second_column_whatever_it_means():
    """In the hard-drinks table that column is `Spirit type`, and it is the only
    thing saying which shared bottle shot a `*(reuse …)*` row belongs to. Losing
    it puts the rum photo on a whisky."""
    rows = _by_item(prompt_sheet.parse(SHEET))

    assert rows["8848 Vodka"]["col2"] == "Vodka"
    assert rows["Ruslan Vodka"]["col2"] == "Vodka"
    assert rows["Black Tea"]["col2"] == "—"


def test_ignores_prose_blockquotes_and_separator_rows():
    rows = prompt_sheet.parse(SHEET)

    items = [r["item"] for r in rows]
    assert items == ["Black Tea", "Milk Tea", "Simple Breakfast",
                     "Mint, Double Apple", "Extra Coil",
                     "Ruslan Vodka", "8848 Vodka"]


def test_ignores_tables_outside_a_section_heading():
    """The sheet's own `Suggested settings` table lives under `## How to use
    these prompts` with no `###` section — its rows are not menu items."""
    rows = prompt_sheet.parse(SHEET)

    assert "Model" not in _by_item(rows)
    assert "Aspect ratio" not in _by_item(rows)


def test_drink_sections_get_the_drink_style_block():
    rows = _by_item(prompt_sheet.parse(SHEET))

    full = prompt_sheet.full_prompt(rows["Black Tea"])
    assert full.startswith("a clear glass cup of strong black tea, no milk,")
    assert "beverage photography" in full
    assert "food photography" not in full


def test_food_sections_get_the_food_style_block():
    rows = _by_item(prompt_sheet.parse(SHEET))

    full = prompt_sheet.full_prompt(rows["Simple Breakfast"])
    assert "food photography" in full
    assert "beverage photography" not in full


def test_hard_drinks_counts_as_a_drink_section():
    rows = _by_item(prompt_sheet.parse(SHEET))

    assert "beverage photography" in prompt_sheet.full_prompt(rows["Ruslan Vodka"])


def test_every_row_carries_an_item_slug():
    rows = _by_item(prompt_sheet.parse(SHEET))

    assert rows["Mint, Double Apple"]["slug"] == "mint-double-apple"


def test_the_dedup_key_is_section_qualified():
    """Bare item names repeat across sections — the real sheet has `Banana`
    under both Milk Shake and Pancakes, which are different pictures. The key
    that decides "already generated" must not collide."""
    sheet = SHEET + """
### Milk Shake

| Item | Printed description | Image prompt |
|---|---|---|
| Banana | — | a tall glass of banana milkshake |

### Pancakes

| Item | Printed description | Image prompt |
|---|---|---|
| Banana | — | a stack of pancakes topped with banana slices |
"""
    keys = [r["key"] for r in prompt_sheet.parse(sheet) if r["item"] == "Banana"]

    assert keys == ["milk-shake-banana", "pancakes-banana"]
