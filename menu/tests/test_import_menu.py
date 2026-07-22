import json
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from menu.models import Company, Branch
from menu.tenancy import set_current_company, reset_current_company


@pytest.fixture
def company(db):
    c = Company.objects.create(name="Tranquility Inn", slug="tranquility-inn")
    Branch.all_objects.create(company=c, slug="restaurant", name="Restaurant", address="")
    token = set_current_company(c)
    yield c
    reset_current_company(token)


def _write_fixture(tmp_path, data):
    p = tmp_path / "fix.json"
    p.write_text(json.dumps(data))
    return str(p)


def test_missing_company_is_hard_error(db, tmp_path):
    fixture = _write_fixture(tmp_path, {"company": "ghost", "categories": [], "items": []})
    with pytest.raises(CommandError, match="No company with slug 'ghost'"):
        call_command("import_menu", "--company", "ghost", "--fixture", fixture)


def test_unknown_branch_is_hard_error(company, tmp_path):
    fixture = _write_fixture(tmp_path, {"company": "tranquility-inn", "categories": [], "items": []})
    with pytest.raises(CommandError, match="Branch 'spa' not found"):
        call_command("import_menu", "--company", "tranquility-inn",
                     "--branch", "spa", "--fixture", fixture)


def test_dry_run_writes_nothing(company, tmp_path):
    fixture = _write_fixture(tmp_path, {
        "company": "tranquility-inn",
        "categories": [{"slug": "starters", "name": "Starters", "display_order": 1,
                        "icon_key": "", "hours_note": "", "subcategories": []}],
        "items": []})
    call_command("import_menu", "--company", "tranquility-inn",
                 "--fixture", fixture, "--dry-run")
    from menu.models import Category
    assert Category.all_objects.filter(company=company).count() == 0
