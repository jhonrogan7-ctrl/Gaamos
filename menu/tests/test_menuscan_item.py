import pytest

from menu.models import Item, MenuScan


@pytest.mark.django_db
def test_menuscan_defaults():
    scan = MenuScan.objects.create(file="scans/x.pdf", source_cafe="Thamel Cafe")
    assert scan.status == "queued"
    assert scan.raw_extraction == {}


@pytest.mark.django_db
def test_item_roundtrips_with_embedding_and_scan():
    scan = MenuScan.objects.create(file="scans/x.pdf", source_cafe="Thamel Cafe")
    item = Item.objects.create(
        name="Black Tea", description="hot milk tea", category="Hot Drinks",
        reference_price=50, embedding=[0.1] * 768, source_scan=scan)
    fetched = Item.objects.get(pk=item.pk)
    assert fetched.status == "active"
    assert fetched.reference_price == 50
    assert list(fetched.embedding) == [pytest.approx(0.1)] * 768
    assert fetched.source_scan_id == scan.pk
    assert fetched.image_asset is None
