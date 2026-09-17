from django.test import override_settings

from menu import sms


def test_send_sms_returns_false_when_unconfigured():
    with override_settings(NEPALOTP_API_KEY="", NEPALOTP_SENDER_ID="", NEPALOTP_URL=""):
        assert sms.send_sms("+9779800000000", "hi") is False


@override_settings(
    NEPALOTP_API_KEY="test-key",
    NEPALOTP_SENDER_ID="GAAMOS",
    NEPALOTP_URL="https://example.test/send",
)
def test_send_sms_returns_true_and_payload_has_text_and_sender(monkeypatch):
    captured = {}

    def fake_post(payload):
        captured["payload"] = payload
        return True

    monkeypatch.setattr(sms, "_post", fake_post)

    assert sms.send_sms("+9779800000000", "your code is 1234") is True
    assert captured["payload"]["message"] == "your code is 1234" or "your code is 1234" in str(captured["payload"])
    assert "GAAMOS" in str(captured["payload"])


@override_settings(
    NEPALOTP_API_KEY="",
    NEPALOTP_SENDER_ID="GAAMOS",
    NEPALOTP_URL="https://example.test/send",
)
def test_send_sms_returns_false_when_partially_unconfigured():
    assert sms.send_sms("+9779800000000", "hi") is False


@override_settings(
    NEPALOTP_API_KEY="test-key",
    NEPALOTP_SENDER_ID="GAAMOS",
    NEPALOTP_URL="https://example.test/send",
)
def test_send_sms_returns_false_and_does_not_raise_on_post_error(monkeypatch):
    def fake_post(payload):
        raise RuntimeError("network down")

    monkeypatch.setattr(sms, "_post", fake_post)

    assert sms.send_sms("+9779800000000", "hi") is False
