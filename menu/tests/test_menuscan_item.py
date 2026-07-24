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
    assert fetched.status == "draft"   # extraction writes drafts; review promotes
    assert fetched.reference_price == 50
    assert list(fetched.embedding) == [pytest.approx(0.1)] * 768
    assert fetched.source_scan_id == scan.pk
    assert fetched.image_asset is None


@pytest.mark.django_db
def test_item_carries_the_canonical_fields():
    scan = MenuScan.objects.create(file="scans/x.pdf", source_cafe="Kailash Parbat")
    item = Item.objects.create(
        name="Ruslan Vodka (Qtr.)", base_name="Ruslan Vodka", variant_label="Qtr.",
        category="Hard Drinks", tags=["ruslan", "vodka"], dietary_tags=["veg"],
        reference_price=850, currency="NPR", source_scan=scan, source_page=2,
        raw_name="Ruslan Vodka", raw_price_text="300    850",
        raw_section="HARD DRINKS", split_from="", confidence=0.92)
    fetched = Item.objects.get(pk=item.pk)
    assert fetched.base_name == "Ruslan Vodka"
    assert fetched.variant_label == "Qtr."
    assert fetched.tags == ["ruslan", "vodka"]
    assert fetched.dietary_tags == ["veg"]
    assert fetched.currency == "NPR"
    assert fetched.source_page == 2
    assert fetched.raw_price_text == "300    850"
    assert fetched.raw_section == "HARD DRINKS"
    assert fetched.confidence == 0.92
    assert fetched.needs_review is False
    assert fetched.merged_into is None


@pytest.mark.django_db
def test_item_defaults_are_lean():
    item = Item.objects.create(name="Black Tea")
    assert item.status == "draft"
    assert item.tags == []
    assert item.dietary_tags == []
    assert item.currency == "NPR"
    assert item.reference_price is None


@pytest.mark.django_db
def test_merged_item_points_at_its_survivor():
    """D2: the one-layer model's provenance fix — a duplicate row survives as
    evidence that a second venue also sells this, instead of being discarded."""
    keeper = Item.objects.create(name="Chicken Momo", status="active")
    dupe = Item.objects.create(name="Chicken Mo:Mo", status="merged", merged_into=keeper)
    assert dupe.merged_into_id == keeper.pk
    assert list(keeper.merged_from.all()) == [dupe]


@pytest.mark.django_db
def test_menuscan_accepts_reviewed_status():
    scan = MenuScan.objects.create(file="scans/x.pdf", status="reviewed")
    assert scan.status == "reviewed"
    assert "reviewed" in dict(MenuScan.STATUS_CHOICES)


@pytest.mark.django_db
def test_scan_tracks_its_image_job_separately_from_extraction():
    scan = MenuScan.objects.create(file='scans/x.pdf', task_id='extract-1',
                                   image_task_id='images-1')
    scan.refresh_from_db()
    assert scan.task_id == 'extract-1'
    assert scan.image_task_id == 'images-1'


@pytest.mark.django_db
def test_image_task_id_defaults_to_blank_not_null():
    scan = MenuScan.objects.create(file='scans/x.pdf')
    scan.refresh_from_db()
    assert scan.image_task_id == ''


def test_scan_image_source_setting_is_a_known_photo_source():
    from django.conf import settings

    from menu.pipeline import photo_search

    assert settings.SCAN_IMAGE_SOURCE in photo_search.SOURCES
