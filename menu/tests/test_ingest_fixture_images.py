import json

import pytest
from django.core.management import call_command

from menu.models import ImageAsset

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _write_fixture(tmp_path, media_dir):
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / "black-tea.webp").write_bytes(PNG)
    (media_dir / "san-miguel.webp").write_bytes(PNG + b"x")
    fixture = {
        "company": "tranquility-inn",
        "items": [
            {"name": "Black Tea", "slug": "black-tea", "cat": "hot-drinks",
             "description": "", "tags": [],
             "image": {"file": "black-tea.webp", "source": "pexels",
                       "origin_url": "https://pexels.com/p/1", "prompt": None}},
            {"name": "San Miguel", "slug": "san-miguel", "cat": "beer",
             "description": "", "tags": [],
             "image": {"file": "san-miguel.webp", "source": "found",
                       "origin_url": "https://commons.example/sm", "prompt": None}},
            {"name": "No Image Item", "slug": "no-image", "cat": "x"},  # skipped
        ],
    }
    path = tmp_path / "fx.json"
    path.write_text(json.dumps(fixture))
    return path


@pytest.mark.django_db
def test_ingest_creates_pending_assets_with_mapped_source_and_tags(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    media_dir = tmp_path / "imgs"
    fixture = _write_fixture(tmp_path, media_dir)

    call_command("ingest_fixture_images", "--fixture", str(fixture),
                 "--media-dir", str(media_dir))

    assert ImageAsset.objects.count() == 2               # the item with no image is skipped
    tea = ImageAsset.objects.get(found_for_slug="black-tea")
    assert tea.status == "pending"
    assert tea.source == "pexels"
    assert tea.origin_url == "https://pexels.com/p/1"
    assert tea.name == "black-tea.webp"
    assert tea.embedding is None                          # default = no embedding
    assert "hot-drinks" in tea.tags and "tea" in tea.tags  # category + slug word

    sm = ImageAsset.objects.get(found_for_slug="san-miguel")
    assert sm.source == "commons"                         # 'found' → 'commons'


@pytest.mark.django_db
def test_ingest_is_idempotent(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    media_dir = tmp_path / "imgs"
    fixture = _write_fixture(tmp_path, media_dir)

    call_command("ingest_fixture_images", "--fixture", str(fixture),
                 "--media-dir", str(media_dir))
    call_command("ingest_fixture_images", "--fixture", str(fixture),
                 "--media-dir", str(media_dir))

    assert ImageAsset.objects.count() == 2               # re-run adds nothing
