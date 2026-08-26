import logging
import urllib.parse
import urllib.request

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def notify_new_lead(self, lead_id):
    """Post a Telegram alert to the team when a new landing lead is captured.

    Fail-soft by design: the notification runs out of band (enqueued on commit),
    so a delivery error never touches lead capture. Retried a few times, then
    logged and dropped. Cleanly disabled when the token or chat id are unset,
    which is how stage stays quiet unless deliberately pointed at a chat.
    """
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.LEAD_NOTIFY_CHAT_ID
    if not (token and chat_id):
        return "skipped: telegram not configured"

    from .models import Lead
    try:
        lead = Lead.objects.get(pk=lead_id)
    except Lead.DoesNotExist:
        return "skipped: lead gone"

    lines = [
        "🔔 New Gaamos lead",
        f"👤 {lead.name}",
        f"🏠 {lead.venue_name} ({lead.get_venue_type_display()})",
        f"📞 {lead.phone}",
    ]
    if lead.email:
        lines.append(f"✉️ {lead.email}")
    if lead.message:
        lines.append(f"💬 {lead.message}")

    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": "\n".join(lines),
        "disable_web_page_preview": "true",
    }).encode()
    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    try:
        with urllib.request.urlopen(url, data=data, timeout=10) as resp:
            resp.read()
    except Exception as exc:  # network / API error — retry, then give up quietly
        logger.warning("lead telegram notify failed: %s", exc)
        raise self.retry(exc=exc)
    return "sent"
