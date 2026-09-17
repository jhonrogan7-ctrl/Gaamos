from datetime import timedelta

import pytest
from django.utils import timezone

from menu.models import Company, Branch, GuestSession, OtpChallenge
from menu.tenancy import set_current_company
from menu.otp import issue_code, verify_code


def _make_session():
    co = Company.objects.create(name="Cafe", slug="cafe")
    set_current_company(co)
    br = Branch.objects.create(company=co, name="Main", address="x")
    gs = GuestSession.objects.create(branch=br, token="t0001", label="Guest A")
    return gs


@pytest.mark.django_db
def test_issue_code_returns_four_digit_string():
    gs = _make_session()
    code = issue_code(gs, "9800000000")
    assert isinstance(code, str)
    assert len(code) == 4
    assert code.isdigit()


@pytest.mark.django_db
def test_issue_code_stores_hashed_challenge_not_raw():
    gs = _make_session()
    code = issue_code(gs, "9800000000")
    ch = OtpChallenge.objects.filter(session=gs).order_by('-id').first()
    assert ch is not None
    assert ch.phone == "9800000000"
    assert ch.code_hash != code
    assert code not in ch.code_hash
    assert ch.attempts == 0


@pytest.mark.django_db
def test_verify_code_correct_code_succeeds():
    gs = _make_session()
    code = issue_code(gs, "9800000000")
    assert verify_code(gs, code) is True
    gs.refresh_from_db()
    assert gs.verified is True
    assert gs.contact == "9800000000"


@pytest.mark.django_db
def test_verify_code_wrong_code_fails():
    gs = _make_session()
    issue_code(gs, "9800000000")
    assert verify_code(gs, "0000") is False
    gs.refresh_from_db()
    assert gs.verified is False


@pytest.mark.django_db
def test_verify_code_false_when_no_challenge():
    gs = _make_session()
    assert verify_code(gs, "1234") is False


@pytest.mark.django_db
def test_verify_code_false_after_expiry():
    gs = _make_session()
    code = issue_code(gs, "9800000000")
    OtpChallenge.objects.filter(session=gs).update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )
    assert verify_code(gs, code) is False


@pytest.mark.django_db
def test_verify_code_false_after_five_wrong_attempts():
    gs = _make_session()
    code = issue_code(gs, "9800000000")
    for _ in range(5):
        assert verify_code(gs, "0000") is False
    # even the correct code now fails: attempts cap reached
    assert verify_code(gs, code) is False


@pytest.mark.django_db
def test_verify_code_latest_challenge_wins():
    gs = _make_session()
    issue_code(gs, "9800000000")
    code2 = issue_code(gs, "9811111111")
    assert verify_code(gs, code2) is True
    gs.refresh_from_db()
    assert gs.contact == "9811111111"
