"""The review page is the only thing standing between a generated image and a
guest's phone, so it has to show what a reviewer needs to spot a mismatch:
the picture, the printed name and price, and the prompt that produced it."""
import io

import pytest
from django.core.management import CommandError, call_command
from PIL import Image

from menu.models import ImageAsset

SHEET = """## Venue

| Field | Value |
|---|---|
| slug | chillzone |
| name | Chill Zone |

## Card 1

### Hot Drinks

| Item | Description | Price | Image prompt |
|---|---|---|---|
| Black Tea | Strong black tea. | 40 | a glass of black tea |

### Egg (2Eggs)

| Item | Description | Price | Image prompt |
|---|---|---|---|
| Boiled Egg | Two boiled eggs. | 120 | two boiled eggs on a plate |
"""


@pytest.fixture
def sheet(tmp_path):
    path = tmp_path / "sheet.md"
    path.write_text(SHEET)
    return str(path)


def _asset(key, media_root, prompt="a glass of black tea, no props", *,
           status="pending", tag="", colour=(10, 20, 30)):
    rel = f"imagelib/{key}{tag}.webp"
    dest = media_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), colour).save(buf, "WEBP")
    dest.write_bytes(buf.getvalue())
    return ImageAsset.objects.create(source="flux", file=rel, status=status,
                                     found_for_slug=key, content_hash=key + tag,
                                     name=key, prompt=prompt)


@pytest.mark.django_db
def test_the_page_carries_name_price_and_prompt_beside_the_image(sheet, settings,
                                                                tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    _asset("hot-drinks-black-tea", tmp_path / "media")
    out = tmp_path / "review.html"

    call_command("review_images", "--prompts", sheet, "--company", "chillzone",
                 "--out", str(out))

    html = out.read_text()
    assert "Black Tea" in html
    assert "Rs 40" in html
    assert "a glass of black tea, no props" in html
    assert "hot-drinks-black-tea" in html


@pytest.mark.django_db
def test_images_are_inlined_so_the_page_stands_alone(sheet, settings, tmp_path):
    """No server, no relative paths — the founder opens one file."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    _asset("hot-drinks-black-tea", tmp_path / "media")
    out = tmp_path / "review.html"

    call_command("review_images", "--prompts", sheet, "--company", "chillzone",
                 "--out", str(out))

    assert "data:image/webp;base64," in out.read_text()


@pytest.mark.django_db
def test_an_item_with_no_asset_is_listed_as_missing(sheet, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    _asset("hot-drinks-black-tea", tmp_path / "media")
    out = tmp_path / "review.html"

    call_command("review_images", "--prompts", sheet, "--company", "chillzone",
                 "--out", str(out))

    assert "Boiled Egg" in out.read_text()


@pytest.mark.django_db
def test_reviewing_changes_no_rows(sheet, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    _asset("hot-drinks-black-tea", tmp_path / "media")

    call_command("review_images", "--prompts", sheet, "--company", "chillzone",
                 "--out", str(tmp_path / "review.html"))

    assert ImageAsset.objects.filter(status="pending").count() == 1


@pytest.mark.django_db
def test_a_sheet_slug_that_disagrees_with_company_is_refused(sheet, settings,
                                                             tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")

    with pytest.raises(CommandError):
        call_command("review_images", "--prompts", sheet, "--company",
                     "tranquilityinn", "--out", str(tmp_path / "r.html"))


@pytest.mark.django_db
def test_the_page_shows_the_rerolled_image_not_the_rejected_one(sheet, settings,
                                                               tmp_path):
    """A re-roll adds a row and leaves the rejected one in place, both sharing
    `found_for_slug`. Showing the older, rejected image would make the re-roll
    invisible and the review loop unable to converge."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    _asset("hot-drinks-black-tea", tmp_path / "media", "the rejected image",
           status="rejected", tag="-old", colour=(200, 10, 10))
    _asset("hot-drinks-black-tea", tmp_path / "media", "the re-rolled image",
           status="pending", tag="-new", colour=(10, 200, 10))
    out = tmp_path / "review.html"

    call_command("review_images", "--prompts", sheet, "--company", "chillzone",
                 "--out", str(out))

    html = out.read_text()
    assert "the re-rolled image" in html
    assert "the rejected image" not in html
