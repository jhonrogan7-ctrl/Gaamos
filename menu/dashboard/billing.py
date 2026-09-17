"""Pure per-table bill-computation helpers (Task 3.1).

These read through the normal (tenant-scoped) managers, so they rely on the
caller having activated the request's company context; they do not touch
views or templates. Integer Rs throughout.
"""
from django.db.models import F, IntegerField, Sum

from menu.models import GuestSession, OrderItem


def table_sessions(branch, table):
    """The open (not yet closed) guest sessions for a branch+table, oldest first."""
    return list(
        GuestSession.objects
        .filter(branch=branch, table=table, closed_at__isnull=True)
        .order_by('created_at')
    )


def session_lines(session):
    """That session's order items aggregated across all its orders, grouped by
    item name: a list of (name, qty, line_total) tuples.

    Sum(unit_price * qty) isn't expressible as Sum('unit_price') * Sum('qty'),
    so the per-row product is summed via an expression instead. The annotation
    aliases below are deliberately not named 'qty' — that would shadow the
    model field of the same name, so a later F('qty') in the same annotate()
    call would resolve to the aggregate instead of the raw field.
    """
    rows = (
        OrderItem.objects
        .filter(order__guest_session=session)
        .values('name')
        .annotate(
            total_qty=Sum('qty'),
            total_line=Sum(F('unit_price') * F('qty'), output_field=IntegerField()),
        )
        .order_by('name')
    )
    return [(row['name'], row['total_qty'], row['total_line']) for row in rows]


def session_subtotal(session):
    """Sum of that session's line totals (Rs)."""
    return sum(line_total for _, _, line_total in session_lines(session))


def table_total(branch, table):
    """Sum of all open sessions' subtotals at the table (Rs)."""
    return sum(session_subtotal(session) for session in table_sessions(branch, table))
