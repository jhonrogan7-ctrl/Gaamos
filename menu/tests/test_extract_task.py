"""The scan task.

These tests patch `extract_nv` rather than `extract` because NVIDIA is the
default backend: they are about what the task does with a payload — normalizing
drafts, surviving a half-written rewrite, recording a failure — not about which
vendor produced it. The three at the bottom are the ones that care which
adapter runs.
"""
from unittest.mock import patch

import pytest

from menu.models import Item, MenuScan
from menu.tasks import extract_menu_scan

MENU = {
    "pages": [{"index": 1, "page_type": "menu", "confidence": 0.95}],
    "items": [
        {"name": "Black Tea", "raw_name": "Black Tea", "category": "Hot Drinks",
         "description": "hot milk tea", "price": 50, "tags": ["black", "tea"],
         "dietary_tags": ["veg"], "source_page": 1, "confidence": 0.95},
        {"name": "Ruslan Vodka (Qtr.)", "base_name": "Ruslan Vodka",
         "variant_label": "Qtr.", "raw_name": "Ruslan Vodka",
         "raw_price_text": "300    850", "raw_section": "HARD DRINKS",
         "category": "Hard Drinks", "price": 850, "source_page": 2,
         "confidence": 0.9},
    ],
}


def _emb(vec):
    return lambda text: vec


def _scan(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    (tmp_path / "scans").mkdir(exist_ok=True)
    (tmp_path / "scans" / "m.pdf").write_bytes(b"PDF")
    return MenuScan.objects.create(file="scans/m.pdf", source_cafe="Cafe",
                                   status="queued")


@pytest.mark.django_db
def test_task_extracts_and_marks_extracted(tmp_path, settings):
    scan = _scan(tmp_path, settings)
    with patch("menu.pipeline.extract_nv.extract_menu", return_value=MENU) as m, \
         patch("menu.pipeline.item_embed.PROVIDER", _emb([0.1] * 1024)):
        extract_menu_scan(scan.id)
    m.assert_called_once()
    scan.refresh_from_db()
    assert scan.status == "extracted"
    assert scan.raw_extraction == MENU


@pytest.mark.django_db
def test_task_writes_normalized_draft_items(tmp_path, settings):
    scan = _scan(tmp_path, settings)
    with patch("menu.pipeline.extract_nv.extract_menu", return_value=MENU), \
         patch("menu.pipeline.item_embed.PROVIDER", _emb([0.1] * 1024)):
        extract_menu_scan(scan.id)
    drafts = Item.objects.filter(source_scan=scan).order_by("name")
    assert drafts.count() == 2
    tea = drafts.get(name="Black Tea")
    assert tea.status == "draft"
    assert tea.tags == ["black", "tea"]
    assert tea.dietary_tags == ["veg"]
    assert tea.reference_price == 50
    assert tea.needs_review is False
    assert list(tea.embedding) == [pytest.approx(0.1)] * 1024
    vodka = drafts.get(name="Ruslan Vodka (Qtr.)")
    assert vodka.base_name == "Ruslan Vodka"
    assert vodka.variant_label == "Qtr."
    assert vodka.raw_price_text == "300    850"
    assert vodka.source_page == 2


@pytest.mark.django_db
def test_reextraction_replaces_drafts_but_keeps_reviewed_rows(tmp_path, settings):
    """Idempotency: re-running a scan must never destroy human decisions."""
    scan = _scan(tmp_path, settings)
    with patch("menu.pipeline.extract_nv.extract_menu", return_value=MENU), \
         patch("menu.pipeline.item_embed.PROVIDER", _emb([0.1] * 1024)):
        extract_menu_scan(scan.id)
    approved = Item.objects.filter(source_scan=scan, name="Black Tea").get()
    approved.status = "active"
    approved.save(update_fields=["status"])

    with patch("menu.pipeline.extract_nv.extract_menu", return_value=MENU), \
         patch("menu.pipeline.item_embed.PROVIDER", _emb([0.1] * 1024)):
        extract_menu_scan(scan.id)

    approved.refresh_from_db()
    assert approved.status == "active"                       # survived
    assert Item.objects.filter(source_scan=scan, status="draft").count() == 2
    assert Item.objects.filter(source_scan=scan).count() == 3


@pytest.mark.django_db
def test_screenshot_page_flags_its_items(tmp_path, settings):
    """A screenshot of another restaurant's menu is never silently trusted."""
    scan = _scan(tmp_path, settings)
    payload = {
        "pages": [{"index": 1, "page_type": "screenshot", "confidence": 0.9}],
        "items": [{"name": "Palak Paneer", "raw_name": "Palak Paneer",
                   "price": 10, "currency": "USD", "source_page": 1,
                   "confidence": 0.9}],
    }
    with patch("menu.pipeline.extract_nv.extract_menu", return_value=payload), \
         patch("menu.pipeline.item_embed.PROVIDER", _emb([0.1] * 1024)):
        extract_menu_scan(scan.id)
    item = Item.objects.get(source_scan=scan)
    assert item.needs_review is True
    assert item.currency == "USD"


@pytest.mark.django_db
def test_failed_rewrite_keeps_the_previous_drafts(tmp_path, settings):
    """A re-extraction that dies partway must not leave a half-written scan:
    the previous drafts survive intact rather than being replaced by a fragment."""
    scan = _scan(tmp_path, settings)
    with patch("menu.pipeline.extract_nv.extract_menu", return_value=MENU), \
         patch("menu.pipeline.item_embed.PROVIDER", _emb([0.1] * 1024)):
        extract_menu_scan(scan.id)
    first = set(Item.objects.filter(source_scan=scan).values_list("pk", flat=True))
    assert len(first) == 2

    calls = {"n": 0}

    def flaky(text):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("embed boom")
        return [0.2] * 1024

    with patch("menu.pipeline.extract_nv.extract_menu", return_value=MENU), \
         patch("menu.pipeline.item_embed.PROVIDER", flaky):
        extract_menu_scan(scan.id)

    scan.refresh_from_db()
    assert scan.status == "failed"
    assert set(Item.objects.filter(source_scan=scan).values_list("pk", flat=True)) == first


@pytest.mark.django_db
def test_task_marks_failed_on_error(tmp_path, settings):
    scan = _scan(tmp_path, settings)
    with patch("menu.pipeline.extract_nv.extract_menu", side_effect=RuntimeError("boom")):
        extract_menu_scan(scan.id)
    scan.refresh_from_db()
    assert scan.status == "failed"
    assert "boom" in scan.error
    assert Item.objects.filter(source_scan=scan).count() == 0


@pytest.mark.django_db
def test_extraction_succeeds_with_no_embedder_configured(tmp_path, settings):
    """Phase 1 ships with no 1024-d provider. A scan must still extract and
    write its drafts -- the vector layer is off, not broken (spec D6)."""
    scan = _scan(tmp_path, settings)
    with patch("menu.pipeline.extract_nv.extract_menu", return_value=MENU):
        extract_menu_scan(scan.id)
    scan.refresh_from_db()
    assert scan.status == "extracted"
    drafts = Item.objects.filter(source_scan=scan)
    assert drafts.count() == 2
    assert all(d.embedding is None for d in drafts)


@pytest.mark.django_db
def test_the_backend_setting_selects_the_nvidia_adapter(tmp_path, settings):
    """Gemini is out of prepay credit and every recent scan died on a 429. The
    default backend is the one with a working key."""
    settings.MENU_EXTRACT_BACKEND = 'nvidia'
    scan = _scan(tmp_path, settings)
    with patch('menu.pipeline.extract_nv.extract_menu',
               return_value=MENU) as nvidia, \
         patch('menu.pipeline.extract.extract_menu') as gemini:
        extract_menu_scan(scan.id)
    assert nvidia.called and not gemini.called
    scan.refresh_from_db()
    assert scan.status == 'extracted'


@pytest.mark.django_db
def test_gemini_remains_reachable_as_a_rollback(tmp_path, settings):
    """`extract.py` is kept deliberately: it is the prompt's home and the way
    back if a key situation reverses."""
    settings.MENU_EXTRACT_BACKEND = 'gemini'
    scan = _scan(tmp_path, settings)
    with patch('menu.pipeline.extract.extract_menu', return_value=MENU) as gemini, \
         patch('menu.pipeline.extract_nv.extract_menu') as nvidia:
        extract_menu_scan(scan.id)
    assert gemini.called and not nvidia.called


@pytest.mark.django_db
def test_an_unknown_backend_fails_the_scan_with_a_readable_reason(tmp_path, settings):
    settings.MENU_EXTRACT_BACKEND = 'wishful'
    scan = _scan(tmp_path, settings)
    extract_menu_scan(scan.id)
    scan.refresh_from_db()
    assert scan.status == 'failed'
    assert 'wishful' in scan.error
