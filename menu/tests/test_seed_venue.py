"""`seed_venue` is the tenant shell for any venue: company + branches from the
fixture's venue block, and deliberately nothing else — the catalog is
`import_menu`'s job, and re-seeding must never undo a venue's own edits."""
import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from menu.models import Branch, Category, Company, MenuItem

VENUE = {"slug": "chillzone", "name": "Chill Zone",
         "tagline": "Momo and cold beer", "phone": "9800000000",
         "email": "", "instagram": "chillzone", "facebook": "", "tiktok": "",
         "branches": [{"slug": "main", "name": "Chill Zone",
                       "address": "Thamel, Kathmandu", "tag": "FLAGSHIP"}]}


def _fixture(tmp_path, venue=None, **extra):
    data = {"venue": venue if venue is not None else VENUE,
            "categories": [], "items": []}
    data.update(extra)
    p = tmp_path / "venue.json"
    p.write_text(json.dumps(data))
    return str(p)


def test_creates_the_company_from_the_venue_block(db, tmp_path):
    call_command("seed_venue", "--fixture", _fixture(tmp_path))

    company = Company.objects.get(slug="chillzone")
    assert company.name == "Chill Zone"
    assert company.tagline == "Momo and cold beer"
    assert company.phone == "9800000000"
    assert company.status == "active"


def test_creates_the_branches_from_the_venue_block(db, tmp_path):
    call_command("seed_venue", "--fixture", _fixture(tmp_path))

    branch = Branch.all_objects.get(company__slug="chillzone", slug="main")
    assert branch.name == "Chill Zone"
    assert branch.address == "Thamel, Kathmandu"
    assert branch.tag == "FLAGSHIP"


def test_is_idempotent(db, tmp_path):
    fixture = _fixture(tmp_path)
    call_command("seed_venue", "--fixture", fixture)
    call_command("seed_venue", "--fixture", fixture)

    assert Company.objects.filter(slug="chillzone").count() == 1
    assert Branch.all_objects.filter(company__slug="chillzone").count() == 1


def test_updates_an_existing_tenant_rather_than_duplicating(db, tmp_path):
    call_command("seed_venue", "--fixture", _fixture(tmp_path))
    renamed = dict(VENUE, name="Chill Zone Thamel")

    call_command("seed_venue", "--fixture", _fixture(tmp_path, venue=renamed))

    assert Company.objects.get(slug="chillzone").name == "Chill Zone Thamel"


def test_seeds_no_catalog(db, tmp_path):
    """A catalog wipe here would undo the venue's dashboard edits on re-run."""
    call_command("seed_venue", "--fixture", _fixture(tmp_path))

    company = Company.objects.get(slug="chillzone")
    assert Category.all_objects.filter(company=company).count() == 0
    assert MenuItem.all_objects.filter(company=company).count() == 0


def test_a_venue_block_with_no_slug_is_a_hard_error(db, tmp_path):
    headless = dict(VENUE, slug="")

    with pytest.raises(CommandError, match="venue.slug"):
        call_command("seed_venue", "--fixture", _fixture(tmp_path, venue=headless))


def test_a_fixture_with_no_venue_block_is_a_hard_error(db, tmp_path):
    p = tmp_path / "old.json"
    p.write_text(json.dumps({"company": "chillzone", "categories": [], "items": []}))

    with pytest.raises(CommandError, match="no `venue` block"):
        call_command("seed_venue", "--fixture", str(p))
