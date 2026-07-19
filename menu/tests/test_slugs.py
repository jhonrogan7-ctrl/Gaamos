import pytest
from django.core.exceptions import ValidationError

from menu.models import Company
from menu.slugs import validate_subdomain_slug


@pytest.mark.django_db
@pytest.mark.parametrize("bad", [
    "a",                # too short
    "x" * 41,           # too long
    "Has-Caps", "under_score", "-lead", "trail-", "dou--ble", "spa ce", "ünïcode",
    "www", "admin", "platform", "dashboard",   # reserved
])
def test_rejects_invalid_and_reserved(bad):
    with pytest.raises(ValidationError):
        validate_subdomain_slug(bad)


@pytest.mark.django_db
def test_rejects_taken_slug_any_status():
    Company.objects.create(name="X", slug="takenco", status="suspended")
    with pytest.raises(ValidationError):
        validate_subdomain_slug("takenco")


@pytest.mark.django_db
@pytest.mark.parametrize("ok", ["momohouse", "cafe-42", "a1", "danfe-house-ktm"])
def test_accepts_valid_free_slugs(ok):
    validate_subdomain_slug(ok)   # no exception
