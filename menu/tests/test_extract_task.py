from unittest.mock import patch

import pytest

from menu.models import MenuScan
from menu.tasks import extract_menu_scan

MENU = {"categories": [{"name": "Hot Drinks",
        "items": [{"name": "Black Tea", "description": "", "price": 50}]}]}


@pytest.mark.django_db
def test_task_extracts_and_marks_extracted(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    (tmp_path / "scans").mkdir()
    (tmp_path / "scans" / "m.pdf").write_bytes(b"PDF")
    scan = MenuScan.objects.create(file="scans/m.pdf", source_cafe="Cafe",
                                   status="queued")
    with patch("menu.pipeline.extract.extract_menu", return_value=MENU) as m:
        extract_menu_scan(scan.id)
    m.assert_called_once()
    scan.refresh_from_db()
    assert scan.status == "extracted"
    assert scan.raw_extraction == MENU


@pytest.mark.django_db
def test_task_marks_failed_on_error(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    (tmp_path / "scans").mkdir()
    (tmp_path / "scans" / "m.pdf").write_bytes(b"PDF")
    scan = MenuScan.objects.create(file="scans/m.pdf", status="queued")
    with patch("menu.pipeline.extract.extract_menu", side_effect=RuntimeError("boom")):
        extract_menu_scan(scan.id)
    scan.refresh_from_db()
    assert scan.status == "failed"
    assert "boom" in scan.error
