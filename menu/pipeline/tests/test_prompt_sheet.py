"""The prompt sheet is a hand-written markdown worksheet (vault:
menius/<venue>/…-items-and-image-prompts.md), not a generated file — so the
parser has to tolerate the things a human does to a markdown table."""
import re

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


PRICED_SHEET = """# Chill Zone — Item List + Image Generation Prompts

## Venue

| Field | Value |
|---|---|
| slug | chillzone |
| name | Chill Zone |
| tagline | Momo, coffee and cold beer in Thamel |
| phone | |
| branch.main.name | Chill Zone |
| branch.main.address | Thamel, Kathmandu |
| branch.main.tag | FLAGSHIP |

## Card 1 — Page 1 (left)

### Hot Drinks

| Item | Description | Price | Image prompt |
|---|---|---|---|
| Black Tea | Classic black tea, brewed strong. | 40 | a glass of black tea |
| Milk Tea | Nepali milk tea. | Rs 60 | a glass cup of milk tea |
| Extra Cup | — | | *skip — accessory* |

### Momo

| Item | Description | Price | Image prompt |
|---|---|---|---|
| Jhol Momo (Veg) | Steamed momo in soup. | 200 | veg jhol momo in broth |
| Jhol Momo (Non Veg) | Steamed momo in soup. | 260 | chicken jhol momo in broth |
"""


def test_reads_the_price_column():
    rows = _by_item(prompt_sheet.parse(PRICED_SHEET))

    assert rows["Black Tea"]["price"] == 40
    assert rows["Jhol Momo (Non Veg)"]["price"] == 260


def test_tolerates_a_currency_prefix_on_the_price():
    rows = _by_item(prompt_sheet.parse(PRICED_SHEET))

    assert rows["Milk Tea"]["price"] == 60


def test_a_row_with_no_price_parses_with_price_none():
    """Not importable, but it is still a row on the card — reported, never
    silently dropped."""
    rows = _by_item(prompt_sheet.parse(PRICED_SHEET))

    assert rows["Extra Cup"]["price"] is None


def test_a_sheet_without_a_price_column_still_parses():
    """Tranquility's sheet has no Price column at all."""
    rows = _by_item(prompt_sheet.parse(SHEET))

    assert rows["Black Tea"]["price"] is None


def test_the_prompt_column_is_found_by_header_not_by_position():
    """With a Price column the prompt is the 4th cell, not the 3rd."""
    rows = _by_item(prompt_sheet.parse(PRICED_SHEET))

    assert rows["Black Tea"]["prompt"] == "a glass of black tea"
    assert rows["Extra Cup"]["generatable"] is False


def test_a_plain_description_header_is_still_a_description():
    """Chill Zone's descriptions are ours, so the column is headed
    `Description` rather than `Printed description`."""
    rows = _by_item(prompt_sheet.parse(PRICED_SHEET))

    assert rows["Black Tea"]["description"] == "Classic black tea, brewed strong."


def test_the_venue_table_is_not_parsed_as_menu_items():
    """`## Venue` is not a `###` section, so its rows are not items."""
    items = [r["item"] for r in prompt_sheet.parse(PRICED_SHEET)]

    assert "slug" not in items and "branch.main.name" not in items
    assert items == ["Black Tea", "Milk Tea", "Extra Cup",
                     "Jhol Momo (Veg)", "Jhol Momo (Non Veg)"]


def test_parse_venue_reads_the_identity_block():
    venue = prompt_sheet.parse_venue(PRICED_SHEET)

    assert venue["slug"] == "chillzone"
    assert venue["name"] == "Chill Zone"
    assert venue["tagline"] == "Momo, coffee and cold beer in Thamel"
    assert venue["phone"] == ""


def test_parse_venue_collects_branches_in_appearance_order():
    venue = prompt_sheet.parse_venue(PRICED_SHEET)

    assert venue["branches"] == [{"slug": "main", "name": "Chill Zone",
                                  "address": "Thamel, Kathmandu",
                                  "tag": "FLAGSHIP"}]


def test_parse_venue_defaults_every_missing_field():
    venue = prompt_sheet.parse_venue("## Venue\n\n| Field | Value |\n|---|---|\n"
                                     "| slug | x |\n| name | X |\n")

    assert venue["email"] == "" and venue["instagram"] == ""
    assert venue["branches"] == []


def test_parse_venue_on_a_sheet_with_no_venue_block():
    """Tranquility's sheet predates the block; it must not raise."""
    venue = prompt_sheet.parse_venue(SHEET)

    assert venue["slug"] == "" and venue["branches"] == []


def test_the_section_qualified_key_still_matches_the_fixture_key():
    """The whole join rests on these two strings being equal by construction."""
    from django.utils.text import slugify

    row = _by_item(prompt_sheet.parse(PRICED_SHEET))["Jhol Momo (Veg)"]

    assert row["key"] == f"{slugify(row['section'])}-{slugify(row['item'])}"


# --- style blocks describe camera and light, never food or drink -------------

def _asserted_words(block):
    """The words a style block ASSERTS: whole words, with its `no <x>`
    exclusions removed first.

    Two traps make naive substring matching useless here. The block must be
    allowed to SAY `no garnish` while never ASSERTING `garnish`, so the
    exclusions come out before the check. And `photography` contains `hot`, so
    the check has to be on whole words or every block fails forever.
    """
    positive = re.sub(r'\bno [a-z ]+?(?=,|$)', '', block)
    return set(re.findall(r'[a-z]+', positive.lower()))


def test_style_blocks_assert_no_food_or_drink_content():
    """The guard for spec D2. `fresh vibrant colours` invented garnish on every
    pale dish; `condensation on the glass` served every hot drink cold. A style
    block may describe camera and light and nothing else."""
    banned = {'vibrant', 'appetising', 'appetizing', 'condensation', 'fresh',
              'delicious', 'colourful', 'colorful', 'steaming', 'garnish',
              'crispy', 'juicy', 'hot', 'ice', 'iced', 'cold'}
    for block in (prompt_sheet.FOOD_STYLE, prompt_sheet.DRINK_STYLE):
        assert not (_asserted_words(block) & banned), block


def test_style_blocks_exclude_what_the_card_did_not_print():
    for block in (prompt_sheet.FOOD_STYLE, prompt_sheet.DRINK_STYLE):
        assert 'no garnish' in block
        assert 'no props' in block


def test_hot_drinks_take_the_drink_style_but_it_asserts_no_temperature():
    """`_DRINK_WORDS` contains 'drink', so the section `Hot Drinks` matches.
    That must pick a STYLE, never a serving temperature — temperature comes
    from the item, through the drink lexicon."""
    assert prompt_sheet.is_drink('Hot Drinks') is True
    asserted = _asserted_words(prompt_sheet.DRINK_STYLE)
    assert 'ice' not in asserted
    assert 'hot' not in asserted


def test_a_spirit_section_is_a_drink_section():
    """Chill Zone's bar card names the spirit, never the word "drink": a glass
    of whisky photographed on the food block's rustic wood table is a plated
    dish, not a pour."""
    for section in ('Whisky', 'Rum', 'Vodka', 'Gin', 'Brandy'):
        assert prompt_sheet.is_drink(section) is True, section


def test_a_short_spirit_name_inside_a_food_name_is_not_a_drink_section():
    """`rum` sits inside `Rumali Roti` and `gin` inside `Ginger`, so those two
    match the section slug exactly rather than as a substring."""
    for section in ('Rumali Roti', 'Ginger Chicken'):
        assert prompt_sheet.is_drink(section) is False, section


def test_the_guard_would_catch_the_two_phrases_that_caused_this():
    """The guard is only worth having if it fails on the real regression."""
    assert 'vibrant' in _asserted_words(", fresh vibrant colours, appetising")
    assert 'condensation' in _asserted_words(", condensation on the glass")


# --- the lexicon expands the subject before the style block is appended ------

def _row(item, prompt, section='Momo'):
    rows = prompt_sheet.parse(
        f"### {section}\n\n"
        "| Item | Description | Price | Image prompt |\n"
        "|---|---|---|---|\n"
        f"| {item} | — | 200 | {prompt} |\n")
    return rows[0]


def test_full_prompt_expands_head_words_before_the_style_block():
    out = prompt_sheet.full_prompt(_row('Veg Momo', 'veg momo'))

    assert 'steamed pleated dumplings' in out
    assert out.index('steamed pleated dumplings') < out.index('professional')
    assert out.endswith(prompt_sheet.FOOD_STYLE)


def test_full_prompt_leaves_an_undefined_name_as_the_bare_subject():
    out = prompt_sheet.full_prompt(_row('Siciliana', 'a plate of siciliana',
                                        section='Pizza'))

    assert out == 'a plate of siciliana' + prompt_sheet.FOOD_STYLE


def test_a_hot_drink_gets_its_temperature_from_the_item_not_the_style_block():
    out = prompt_sheet.full_prompt(
        _row('Hot Chocolate', 'a mug of hot chocolate', section='Hot Drinks'))

    assert 'steam rising' in out
    assert out.endswith(prompt_sheet.DRINK_STYLE)


def test_a_food_section_never_gets_a_serving_temperature():
    out = prompt_sheet.full_prompt(
        _row('Hot & Sour Soup', 'a bowl of hot and sour soup', section='Soups'))

    assert 'steam rising' not in out
