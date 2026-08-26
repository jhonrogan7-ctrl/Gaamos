import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Lead
from .tasks import notify_new_lead

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Lead)
def lead_created(sender, instance, created, **kwargs):
    """Fire a Telegram alert once a new lead is safely committed.

    on_commit avoids a race where the worker reads the row before the request's
    transaction lands; the try/except keeps a broker hiccup from ever bubbling
    into (and failing) the guest's form submission.
    """
    if not created:
        return

    def _enqueue():
        try:
            notify_new_lead.delay(instance.pk)
        except Exception:
            logger.exception("lead notify enqueue failed")

    transaction.on_commit(_enqueue)
