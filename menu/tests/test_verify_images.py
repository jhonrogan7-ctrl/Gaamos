"""Applying the verdict. Everything not rejected is verified — a reviewer who
looked at the page and rejected nothing has approved it, and that has to be
recorded, because `--require-verified` reads exactly this field."""
import io

import pytest
from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from PIL import Image

from menu.models import ImageAsset

from menu.tests.test_review_images import SHEET


@pytest.fixture
def sheet(tmp_path):
    path = tmp_path / "sheet.md"
    path.write_text(SHEET)
    return str(path)


def _asset(key, media_root, *, status="pending", tag=""):
    rel = f"imagelib/{key}{tag}.webp"
    dest = media_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (10, 20, 30)).save(buf, "WEBP")
    dest.write_bytes(buf.getvalue())
    return ImageAsset.objects.create(source="flux", file=rel, status=status,
                                     found_for_slug=key, content_hash=key + tag,
                                     name=key)


@pytest.mark.django_db
def test_listed_keys_are_rejected_and_the_rest_verified(sheet, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    _asset("hot-drinks-black-tea", tmp_path / "media")
    _asset("egg-2eggs-boiled-egg", tmp_path / "media")

    call_command("verify_images", "--prompts", sheet, "--company", "chillzone",
                 "--reject", "egg-2eggs-boiled-egg")

    assert ImageAsset.objects.get(
        found_for_slug="egg-2eggs-boiled-egg").status == "rejected"
    assert ImageAsset.objects.get(
        found_for_slug="hot-drinks-black-tea").status == "verified"


@pytest.mark.django_db
def test_the_review_is_stamped(sheet, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    _asset("hot-drinks-black-tea", tmp_path / "media")
    user = User.objects.create_user("founder")

    call_command("verify_images", "--prompts", sheet, "--company", "chillzone",
                 "--user", "founder")

    asset = ImageAsset.objects.get(found_for_slug="hot-drinks-black-tea")
    assert asset.reviewed_at is not None
    assert asset.reviewed_by == user


@pytest.mark.django_db
def test_an_asset_outside_this_sheet_is_never_touched(sheet, settings, tmp_path):
    """The pool is shared across venues; verifying Chill Zone must not sign off
    on Tranquility."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    _asset("hot-drinks-black-tea", tmp_path / "media")
    _asset("a-la-carte-breakfast-aloo-paratha", tmp_path / "media")

    call_command("verify_images", "--prompts", sheet, "--company", "chillzone")

    assert ImageAsset.objects.get(
        found_for_slug="a-la-carte-breakfast-aloo-paratha").status == "pending"


@pytest.mark.django_db
def test_an_unknown_reject_key_is_refused(sheet, settings, tmp_path):
    """A typo in a pasted key must not silently verify the image it meant to
    reject."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    _asset("hot-drinks-black-tea", tmp_path / "media")

    with pytest.raises(CommandError) as exc:
        call_command("verify_images", "--prompts", sheet, "--company",
                     "chillzone", "--reject", "egg-2eggs-boild-egg")

    assert "egg-2eggs-boild-egg" in str(exc.value)


@pytest.mark.django_db
def test_an_unknown_user_is_refused(sheet, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    _asset("hot-drinks-black-tea", tmp_path / "media")

    with pytest.raises(CommandError):
        call_command("verify_images", "--prompts", sheet, "--company",
                     "chillzone", "--user", "nobody")


@pytest.mark.django_db
def test_a_rejected_tombstone_is_never_flipped_back_to_verified(sheet, settings,
                                                                tmp_path):
    """`intake.record` reads a rejected row to refuse serving those bytes ever
    again. Verifying the re-rolled image must not resurrect the one it replaced."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    _asset("hot-drinks-black-tea", tmp_path / "media", status="rejected",
           tag="-old")
    _asset("hot-drinks-black-tea", tmp_path / "media", status="pending",
           tag="-new")

    call_command("verify_images", "--prompts", sheet, "--company", "chillzone")

    statuses = sorted(ImageAsset.objects
                      .filter(found_for_slug="hot-drinks-black-tea")
                      .values_list("status", flat=True))
    assert statuses == ["rejected", "verified"]
