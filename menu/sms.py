import json
import logging
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)


def _build_payload(phone, text):
    """Build the request body for the NepalOTP send-SMS call.

    NOTE: NepalOTP's exact field names are not yet known (Janak will provide
    the real account docs — see dev-notes/2026-08-25-otp-sms-providers-nepal.md).
    This is the single place to update once that arrives; everything else in
    this module treats the payload as an opaque dict.
    """
    return {
        "api_key": settings.NEPALOTP_API_KEY,
        "sender_id": settings.NEPALOTP_SENDER_ID,
        "to": phone,
        "message": text,
    }


def _post(payload):
    """Issue the actual HTTP request to NepalOTP. Isolated so tests can
    monkeypatch it without touching the network, and so this is the single
    place to adjust once the real NepalOTP endpoint/response shape is known.
    """
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        settings.NEPALOTP_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()
    return True


def send_sms(phone, text):
    """Send one SMS via NepalOTP. Fail-soft by design: never raises.

    Returns False (and logs a warning) when unconfigured or on any
    network/API error, so callers can fire this without wrapping it in
    their own try/except.
    """
    if not (settings.NEPALOTP_API_KEY and settings.NEPALOTP_SENDER_ID and settings.NEPALOTP_URL):
        return False

    payload = _build_payload(phone, text)
    try:
        _post(payload)
    except Exception as exc:  # network / API error — log and give up quietly
        logger.warning("NepalOTP send_sms failed: %s", exc)
        return False
    return True
