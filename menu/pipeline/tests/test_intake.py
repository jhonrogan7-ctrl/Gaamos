import pytest

from menu.models import ImageAsset
from menu.pipeline import intake

PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)  # opaque bytes; intake stores as-is


def _embedder(text):
    return [0.2] * 768


@pytest.mark.django_db
def test_record_creates_pending_asset_with_caption_and_embedding(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    asset = intake.record(source="pexels", webp_bytes=PNG, item_name="Boiled Egg",
                          found_for_slug="boiled-egg", source_text="egg on plate",
                          origin_url="https://x/egg.jpg", embedder=_embedder)
    assert asset.status == "pending"
    assert asset.source == "pexels"
    assert "Boiled Egg" in asset.caption and "egg on plate" in asset.caption
    assert list(asset.embedding) == [0.2] * 768
    assert asset.file.startswith("imagelib/") and asset.file.endswith(".webp")
    assert (tmp_path / asset.file).read_bytes() == PNG


@pytest.mark.django_db
def test_record_dedups_on_origin_url(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    a = intake.record(source="pexels", webp_bytes=PNG, item_name="Egg",
                      found_for_slug="egg", origin_url="https://x/egg.jpg",
                      embedder=_embedder)
    b = intake.record(source="pexels", webp_bytes=PNG + b"z", item_name="Egg",
                      found_for_slug="egg", origin_url="https://x/egg.jpg",
                      embedder=_embedder)
    assert a.pk == b.pk
    assert ImageAsset.objects.count() == 1


@pytest.mark.django_db
def test_record_skips_rejected_tombstone(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    ImageAsset.objects.create(source="pexels", origin_url="https://x/bad.jpg",
                              status="rejected")
    result = intake.record(source="pexels", webp_bytes=PNG, item_name="Egg",
                           found_for_slug="egg", origin_url="https://x/bad.jpg",
                           embedder=_embedder)
    assert result is None
    assert ImageAsset.objects.filter(status="pending").count() == 0


@pytest.mark.django_db
def test_record_dedups_generated_on_content_hash(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    a = intake.record(source="gemini", webp_bytes=PNG, item_name="Momo",
                      found_for_slug="momo", prompt="a plate of momo",
                      embedder=_embedder)
    b = intake.record(source="gemini", webp_bytes=PNG, item_name="Momo",
                      found_for_slug="momo", prompt="a plate of momo",
                      embedder=_embedder)
    assert a.pk == b.pk
    assert ImageAsset.objects.count() == 1
