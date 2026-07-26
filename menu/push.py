"""Web Push delivery for dashboard staff.

Only new orders notify, and only the people already entitled to see that order:
owners of the company, plus branch managers assigned to that order's branch.
Recipient resolution mirrors `menu.permissions.visible_branches` — if the two
ever disagree, this file is the one leaking a branch's trade to someone the
dashboard would not show it to.

Sending happens off the request (see `menu.tasks.send_order_push`): delivery
talks to Google/Mozilla push endpoints over the network, and a guest pressing
"place order" must never wait on that.
"""
import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

# Push services expire endpoints silently; these two codes are the documented
# "this registration is dead, stop using it" signal.
_DEAD_STATUSES = (404, 410)


def push_enabled():
    """Push is configured. Without keys the feature is inert, not broken —
    a deployment that never set VAPID keys must still take orders."""
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def recipients_for_order(order):
    """Users entitled to be notified about ``order``.

    Owners see every branch; a manager sees only the branches assigned to them.
    Superusers are deliberately excluded — a platform admin impersonating a
    tenant should not silently collect that tenant's order notifications.

    Runs in a Celery worker, which has **no tenant context**. So this must not
    touch `Branch.objects` (fail-closed, raises without a company): the manager
    check is expressed as a join on the membership M2M, which resolves through
    the model's base manager instead. `prefetch_related('branches')` here was a
    real bug — green under test, exploding in the worker.
    """
    from .models import Membership

    base = Membership.objects.filter(company_id=order.company_id)
    owners = base.filter(role=Membership.ROLE_OWNER).values_list('user_id', flat=True)
    branch_managers = (base.filter(role=Membership.ROLE_MANAGER,
                                   branches__id=order.branch_id)
                       .values_list('user_id', flat=True))
    return list(dict.fromkeys([*owners, *branch_managers]))


def order_payload(order):
    """The notification body. Deliberately small — a push payload is size
    limited, and everything here is already on the staff member's own queue."""
    items = list(order.items.all())
    count = sum(i.qty for i in items)
    where = f"Table {order.table_label}" if order.table_label else 'Takeaway'
    return {
        'title': f"New order · {where}",
        'body': f"{count} item{'s' if count != 1 else ''} · Rs {order.total}",
        'tag': f"order-{order.pk}",       # replaces, never stacks, per order
        'url': '/dashboard/orders/',
        'order_id': order.pk,
    }


SENT, FAILED, DEAD = 'sent', 'failed', 'dead'


def send_to_subscription(sub, payload):
    """Deliver one payload.

    Returns SENT (accepted by the push service), FAILED (transient — keep the
    subscription and try again next order) or DEAD (the service says this
    registration is gone; the caller deletes it).

    The three are kept distinct on purpose: an earlier version folded FAILED
    into SENT, so a run where every delivery errored still reported a healthy
    "sent=N" and there was nothing in the return value to say otherwise.
    """
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info=sub.as_subscription_info(),
            data=json.dumps(payload),
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={'sub': f"mailto:{settings.VAPID_ADMIN_EMAIL}"},
            timeout=10,
        )
        return SENT
    except WebPushException as exc:
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
        if status in _DEAD_STATUSES:
            logger.info('push: dropping expired subscription %s (%s)', sub.pk, status)
            return DEAD
        # Transient (push service down, timeout, malformed key): must not
        # delete a subscription that may well work next time.
        logger.warning('push: send failed sub=%s status=%s: %s', sub.pk, status, exc)
        return FAILED
    except Exception:                                    # noqa: BLE001
        logger.exception('push: unexpected error for sub=%s', sub.pk)
        return FAILED


def notify_new_order(order):
    """Fan out one order to every eligible staff subscription.

    Returns a ``{'sent', 'failed', 'dropped'}`` tally. Never raises: a push
    problem must not fail the order that triggered it.
    """
    from .models import PushSubscription

    tally = {'sent': 0, 'failed': 0, 'dropped': 0}
    if not push_enabled():
        return tally

    user_ids = recipients_for_order(order)
    if not user_ids:
        return tally

    # all_objects: this runs in a Celery worker with no tenant context. The
    # company filter is explicit and is what keeps it scoped.
    subs = list(PushSubscription.all_objects.filter(
        company_id=order.company_id, user_id__in=user_ids))
    if not subs:
        return tally

    payload = order_payload(order)
    dead = []
    for sub in subs:
        result = send_to_subscription(sub, payload)
        if result is DEAD:
            dead.append(sub.pk)
            tally['dropped'] += 1
        elif result is SENT:
            tally['sent'] += 1
        else:
            tally['failed'] += 1

    if dead:
        PushSubscription.all_objects.filter(pk__in=dead).delete()
    return tally
