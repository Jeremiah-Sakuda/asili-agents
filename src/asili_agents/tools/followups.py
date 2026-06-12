"""Follow-up and invoice-nudge detection tools.

The Messaging Agent's highest-value behaviors (per the PRD) are not first
replies — they are chasing the sales that already leaked: threads that went
quiet and invoices that were sent but never paid. The DECISION of *which*
threads and invoices need attention is deterministic and must not be left to the
LLM (it would hallucinate amounts, dates, and who owes what). So detection lives
here as plain functions over a per-seller store, exactly like the catalog and
pricing tools; the agent only writes the nudge copy, grounded in what these
tools return.

The pure ``detect_*`` functions take an explicit ``now`` (fully testable, no
wall-clock). The ``find_*`` tool wrappers the agent calls read the in-process
store and stamp ``now`` themselves.

Store note: in local dev / tests / the demo the store is seeded in-process
(``set_followups_context``). Grounding orders/threads through MongoDB Atlas in
the deployed path is the remaining write-path increment, mirroring how the
decision log and eval runs are still in-process today.
"""

from datetime import UTC, datetime
from typing import Any

from asili_agents.data.models import Conversation, MessageDirection, Order

# Per-seller in-process store. Mirrors set_pricing_context / set_product_store.
_conversations: list[Conversation] = []
_orders: list[Order] = []


def set_followups_context(conversations: list[Conversation], orders: list[Order]) -> None:
    """Seed the follow-up/invoice store (tests, local dev, API startup)."""
    global _conversations, _orders
    _conversations = list(conversations)
    _orders = list(orders)


def clear_followups_context() -> None:
    """Reset the store (test isolation)."""
    set_followups_context([], [])


def detect_quiet_threads(
    conversations: list[Conversation],
    *,
    now: datetime,
    quiet_after_hours: float = 24.0,
) -> list[dict[str, Any]]:
    """Return open threads that have gone quiet past the threshold.

    A thread is a reactivation candidate when it is not CLOSED and no message has
    arrived for longer than ``quiet_after_hours``. ``last_direction`` tells the
    agent what kind of nudge fits: a thread whose last message was OUTBOUND means
    the customer went silent after the seller's reply (re-engage); INBOUND means
    the customer is still waiting (the seller dropped it). Results are sorted
    most-quiet first so the agent works the coldest threads before the warm ones.
    """
    candidates: list[dict[str, Any]] = []
    for conv in conversations:
        if not conv.is_open:
            continue
        hours = conv.hours_quiet(now)
        if hours < quiet_after_hours:
            continue
        last_dir = conv.last_direction
        candidates.append(
            {
                "conversation_id": str(conv.id),
                "customer_name": conv.customer_name,
                "channel": conv.channel,
                "hours_quiet": round(hours, 1),
                "last_direction": last_dir.value if last_dir else None,
                "customer_waiting": last_dir == MessageDirection.INBOUND,
            }
        )
    candidates.sort(key=lambda c: c["hours_quiet"], reverse=True)
    return candidates


def detect_unpaid_invoices(
    orders: list[Order],
    *,
    now: datetime,
    grace_hours: float = 0.0,
) -> list[dict[str, Any]]:
    """Return invoices that were sent but not paid and are past due + grace.

    ``grace_hours`` lets the seller hold off nudging until an invoice is a little
    overdue (e.g. don't chase something sent an hour ago). Amounts are returned as
    exact strings so nudge copy quotes the precise figure. Sorted most-overdue
    first.
    """
    candidates: list[dict[str, Any]] = []
    for order in orders:
        if not order.is_overdue(now):
            continue
        hours_overdue = order.hours_overdue(now)
        if hours_overdue < grace_hours:
            continue
        candidates.append(
            {
                "order_id": str(order.id),
                "customer_name": order.customer_name,
                "description": order.description,
                "amount": str(order.amount),
                "hours_overdue": round(hours_overdue, 1),
                "days_overdue": round(hours_overdue / 24.0, 1),
            }
        )
    candidates.sort(key=lambda c: c["hours_overdue"], reverse=True)
    return candidates


def find_quiet_threads(quiet_after_hours: float = 24.0) -> list[dict[str, Any]]:
    """Find open customer threads that have gone quiet and may need a follow-up.

    Use this BEFORE drafting any re-engagement message, so you only follow up on
    real threads and never invent a conversation. Each result tells you the
    customer, how long it's been quiet, and whether the customer is still waiting
    on you (customer_waiting=true) or went silent after your reply.

    Args:
        quiet_after_hours: How many hours of silence make a thread a candidate
            (default 24).

    Returns:
        Quiet threads, most-quiet first. Empty list if none.
    """
    return detect_quiet_threads(
        _conversations, now=datetime.now(UTC), quiet_after_hours=quiet_after_hours
    )


def find_unpaid_invoices(grace_hours: float = 0.0) -> list[dict[str, Any]]:
    """Find invoices that were sent but not paid and are now overdue.

    Use this BEFORE drafting any payment reminder, so you only nudge real unpaid
    invoices and quote the exact amount owed. Never invent an amount, customer, or
    due date — use only what this tool returns.

    Args:
        grace_hours: Don't surface an invoice until it's at least this many hours
            overdue (default 0).

    Returns:
        Overdue unpaid invoices, most-overdue first, with exact amounts. Empty if
        none.
    """
    return detect_unpaid_invoices(_orders, now=datetime.now(UTC), grace_hours=grace_hours)


__all__ = [
    "clear_followups_context",
    "detect_quiet_threads",
    "detect_unpaid_invoices",
    "find_quiet_threads",
    "find_unpaid_invoices",
    "set_followups_context",
]
