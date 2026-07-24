"""Joining fixture items to generated images.

The two sources drifted: the fixture carries corrected item names, the prompt
sheet carries the names as printed on the card (typos and all). A careless join
pairs a dish with a *different* dish's photo, which on a live menu means guests
are served something other than the picture.
"""
from menu.management.commands.build_venue_fixture import assign_images


def _item(cat, slug, name):
    return {"cat": cat, "slug": slug, "name": name}


def test_exact_key_match_wins():
    items = [_item("hot-drinks", "black-tea", "Black Tea")]

    got = assign_images(items, generated_keys={"hot-drinks-black-tea"},
                        vault_files=[], sheet={})

    assert got["hot-drinks-black-tea"] == ("generated", "hot-drinks-black-tea")


def test_a_printed_typo_still_finds_its_image():
    """Fixture says `bread-omelette`, the card printed `Bread Omellete`."""
    items = [_item("a-la-carte-breakfast", "bread-omelette", "Bread Omelette")]

    got = assign_images(items,
                        generated_keys={"a-la-carte-breakfast-bread-omellete"},
                        vault_files=[], sheet={})

    assert got["a-la-carte-breakfast-bread-omelette"] == \
        ("generated", "a-la-carte-breakfast-bread-omellete")


def test_an_imageless_item_never_steals_another_dishes_photo():
    """`Chicken Fry` has no image of its own and reads as similar to
    `Chicken Finger`, which does. One image, one item — Chicken Fry must come
    away empty rather than wearing the wrong dish."""
    items = [_item("non-veg-snacks", "chicken-finger", "Chicken Finger"),
             _item("non-veg-snacks", "chicken-fry", "Chicken Fry")]

    got = assign_images(items,
                        generated_keys={"non-veg-snacks-chicken-finger"},
                        vault_files=[], sheet={})

    assert got["non-veg-snacks-chicken-finger"] == \
        ("generated", "non-veg-snacks-chicken-finger")
    assert got["non-veg-snacks-chicken-fry"] is None


def test_order_does_not_decide_who_gets_the_image():
    """Same pair, imageless item listed first — the exact match must still win."""
    items = [_item("non-veg-snacks", "chicken-fry", "Chicken Fry"),
             _item("non-veg-snacks", "chicken-finger", "Chicken Finger")]

    got = assign_images(items,
                        generated_keys={"non-veg-snacks-chicken-finger"},
                        vault_files=[], sheet={})

    assert got["non-veg-snacks-chicken-fry"] is None
    assert got["non-veg-snacks-chicken-finger"] == \
        ("generated", "non-veg-snacks-chicken-finger")


def test_uses_the_venues_own_photo_when_there_is_one():
    items = [_item("breakfast", "simple-breakfast", "Simple Breakfast")]

    got = assign_images(items, generated_keys=set(),
                        vault_files=["Simple Breakfast_1.jpg"], sheet={})

    assert got["breakfast-simple-breakfast"] == ("found", "Simple Breakfast_1.jpg")


def test_matches_a_truncated_venue_filename():
    """The venue folder holds `ndian Breakfast_1.jpg` for `Indian Breakfast`."""
    items = [_item("breakfast", "indian-breakfast", "Indian Breakfast")]

    got = assign_images(items, generated_keys=set(),
                        vault_files=["ndian Breakfast_1.jpg"], sheet={})

    assert got["breakfast-indian-breakfast"] == ("found", "ndian Breakfast_1.jpg")


def _spirit(item, col2, prompt, generatable):
    return {"item": item, "section": "Hard Drinks", "col2": col2,
            "prompt": prompt, "generatable": generatable}


def test_reuse_rows_share_the_one_image_their_section_generated():
    """The sheet collapses 18 spirit listings onto 4 images on purpose."""
    items = [_item("hard-drinks", "golden-oak", "Golden Oak"),
             _item("hard-drinks", "jack-daniel-s", "Jack Daniel's")]
    sheet = {
        "hard-drinks-golden-oak": _spirit("Golden Oak", "Whisky",
                                          "a glass of golden whisky", True),
        "hard-drinks-jack-deniels": _spirit("Jack Deniels", "Whisky",
                                            "*(reuse the whisky image)*", False),
    }

    got = assign_images(items, generated_keys={"hard-drinks-golden-oak"},
                        vault_files=[], sheet=sheet)

    assert got["hard-drinks-golden-oak"] == ("generated", "hard-drinks-golden-oak")
    assert got["hard-drinks-jack-daniel-s"] == ("generated", "hard-drinks-golden-oak")


def test_a_whisky_does_not_inherit_the_rum_photo():
    """Rum, vodka and whisky all sit under `Hard Drinks`; only the spirit-type
    column says which shared bottle shot a reuse row belongs to."""
    items = [_item("hard-drinks", "rum", "Rum"),
             _item("hard-drinks", "golden-oak", "Golden Oak"),
             _item("hard-drinks", "jack-daniel-s", "Jack Daniel's")]
    sheet = {
        "hard-drinks-rum": _spirit("Rum", "Rum", "a pour of dark rum", True),
        "hard-drinks-golden-oak": _spirit("Golden Oak", "Whisky",
                                          "a glass of golden whisky", True),
        "hard-drinks-jack-deniels": _spirit("Jack Deniels", "Whisky",
                                            "*(reuse the whisky image)*", False),
    }

    got = assign_images(items,
                        generated_keys={"hard-drinks-rum", "hard-drinks-golden-oak"},
                        vault_files=[], sheet=sheet)

    assert got["hard-drinks-jack-daniel-s"] == ("generated", "hard-drinks-golden-oak")


def test_an_item_with_nothing_anywhere_gets_no_image():
    items = [_item("hookah", "extra-coil", "Extra Coil")]

    got = assign_images(items, generated_keys=set(), vault_files=[], sheet={})

    assert got["hookah-extra-coil"] is None


def test_an_explicit_key_overrides_the_derived_one():
    """A duplicate item name across two sections gets a uniquified item slug,
    so the join key can no longer be derived from cat + slug — the builder
    passes the sheet key the image was named from."""
    items = [{"cat": "pancakes", "slug": "banana-pancakes", "name": "Banana",
              "key": "pancakes-banana"}]

    got = assign_images(items, generated_keys={"pancakes-banana"},
                        vault_files=[], sheet={})

    assert got["pancakes-banana"] == ("generated", "pancakes-banana")


def test_name_drift_is_scoped_to_the_items_own_category():
    """No alias table any more — the category prefix is the category slug."""
    items = [_item("pancakes", "plain-pancake", "Plain Pancake")]

    got = assign_images(items, generated_keys={"pancakes-plain"},
                        vault_files=[], sheet={})

    assert got["pancakes-plain-pancake"] == ("generated", "pancakes-plain")


def test_one_venue_photo_is_not_handed_to_two_items():
    items = [_item("milk-shake-lassi", "banana", "Banana"),
             _item("pancakes", "banana-pancake", "Banana Pancake")]

    got = assign_images(items, generated_keys=set(),
                        vault_files=["Banana.jpg"], sheet={})

    claimed = [v for v in got.values() if v]
    assert claimed == [("found", "Banana.jpg")]
