import pytest

from menu.models import ImageAsset


@pytest.mark.django_db
def test_image_asset_roundtrips_vector_and_defaults():
    asset = ImageAsset.objects.create(
        name="boiled-egg.jpg",
        caption="boiled egg breakfast on plate",
        tags=["boiled-egg", "egg"],
        embedding=[0.1] * 768,
        source="pexels",
        origin_url="https://example.com/egg.jpg",
        file="imagelib/abc123.webp",
        content_hash="abc123",
        found_for_slug="boiled-egg",
    )
    fetched = ImageAsset.objects.get(pk=asset.pk)
    assert fetched.status == "pending"
    assert list(fetched.embedding) == [pytest.approx(0.1)] * 768
    assert fetched.tags == ["boiled-egg", "egg"]
    assert fetched.image_url == "/media/imagelib/abc123.webp"


@pytest.mark.django_db
def test_origin_link_rejects_dangerous_schemes():
    asset = ImageAsset.objects.create(
        source="find", origin_url="javascript:alert(1)")
    assert asset.origin_link == ""


@pytest.mark.django_db
def test_origin_link_passes_through_http_https():
    asset = ImageAsset.objects.create(
        source="find", origin_url="https://example.com/x.jpg")
    assert asset.origin_link == "https://example.com/x.jpg"
