"""Tests for follow-up / unpaid-invoice detection.

Detection is deterministic and must not be left to the LLM, so it gets
deterministic tests with an explicit ``now`` — no wall-clock, no flakiness.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from asili_agents.data.models import (
    Conversation,
    ConversationStatus,
    MessageDirection,
    Order,
    OrderStatus,
)
from asili_agents.data.seed import create_demo_followups
from asili_agents.tools.followups import (
    clear_followups_context,
    detect_quiet_threads,
    detect_unpaid_invoices,
    find_quiet_threads,
    find_unpaid_invoices,
    set_followups_context,
)

NOW = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)
SELLER = uuid4()


def _thread(customer: str, *, last_dir: MessageDirection, hours_ago: float, closed: bool = False):
    conv = Conversation(
        seller_id=SELLER,
        customer_name=customer,
        status=ConversationStatus.CLOSED if closed else ConversationStatus.ACTIVE,
    )
    msg = conv.add_message(direction=last_dir, sender_name=customer, body="hi")
    msg.sent_at = NOW - timedelta(hours=hours_ago)
    return conv


class TestDetectQuietThreads:
    def test_flags_threads_past_threshold_only(self):
        convs = [
            _thread("Quiet", last_dir=MessageDirection.OUTBOUND, hours_ago=50),
            _thread("Fresh", last_dir=MessageDirection.INBOUND, hours_ago=2),
        ]
        out = detect_quiet_threads(convs, now=NOW, quiet_after_hours=24)
        names = [t["customer_name"] for t in out]
        assert names == ["Quiet"]

    def test_excludes_closed_threads(self):
        convs = [_thread("Done", last_dir=MessageDirection.OUTBOUND, hours_ago=100, closed=True)]
        assert detect_quiet_threads(convs, now=NOW, quiet_after_hours=24) == []

    def test_customer_waiting_flag_from_last_direction(self):
        convs = [
            _thread("Waiting", last_dir=MessageDirection.INBOUND, hours_ago=48),
            _thread("WentQuiet", last_dir=MessageDirection.OUTBOUND, hours_ago=48),
        ]
        out = {t["customer_name"]: t for t in detect_quiet_threads(convs, now=NOW)}
        assert out["Waiting"]["customer_waiting"] is True
        assert out["WentQuiet"]["customer_waiting"] is False

    def test_sorted_most_quiet_first(self):
        convs = [
            _thread("A", last_dir=MessageDirection.INBOUND, hours_ago=30),
            _thread("B", last_dir=MessageDirection.INBOUND, hours_ago=90),
            _thread("C", last_dir=MessageDirection.INBOUND, hours_ago=60),
        ]
        out = [t["customer_name"] for t in detect_quiet_threads(convs, now=NOW)]
        assert out == ["B", "C", "A"]


def _invoice(customer, amount, *, status=OrderStatus.INVOICED, due_days_ago=None, paid=False):
    return Order(
        seller_id=SELLER,
        customer_name=customer,
        description="order",
        amount=Decimal(amount),
        status=OrderStatus.PAID if paid else status,
        invoiced_at=NOW - timedelta(days=5),
        due_at=(NOW - timedelta(days=due_days_ago)) if due_days_ago is not None else None,
        paid_at=(NOW - timedelta(days=1)) if paid else None,
    )


class TestDetectUnpaidInvoices:
    def test_flags_overdue_unpaid_only(self):
        orders = [
            _invoice("Overdue", "48.00", due_days_ago=2),
            _invoice("Paid", "18.00", due_days_ago=2, paid=True),
            _invoice("Quoted", "30.00", status=OrderStatus.QUOTED, due_days_ago=2),
        ]
        out = detect_unpaid_invoices(orders, now=NOW)
        assert [i["customer_name"] for i in out] == ["Overdue"]
        assert out[0]["amount"] == "48.00"  # exact, string

    def test_not_yet_due_is_not_flagged(self):
        orders = [_invoice("Future", "20.00", due_days_ago=-3)]  # due in the future
        assert detect_unpaid_invoices(orders, now=NOW) == []

    def test_grace_hours_suppresses_barely_overdue(self):
        # Due 6 hours ago; a 12h grace should suppress it.
        order = Order(
            seller_id=SELLER,
            customer_name="Barely",
            amount=Decimal("10.00"),
            status=OrderStatus.INVOICED,
            invoiced_at=NOW - timedelta(days=1),
            due_at=NOW - timedelta(hours=6),
        )
        assert detect_unpaid_invoices([order], now=NOW, grace_hours=12) == []
        assert len(detect_unpaid_invoices([order], now=NOW, grace_hours=0)) == 1

    def test_no_due_date_overdue_once_invoiced(self):
        order = Order(
            seller_id=SELLER,
            customer_name="NoDue",
            amount=Decimal("25.00"),
            status=OrderStatus.INVOICED,
            invoiced_at=NOW - timedelta(days=2),
        )
        assert len(detect_unpaid_invoices([order], now=NOW)) == 1

    def test_sorted_most_overdue_first(self):
        orders = [
            _invoice("Recent", "10.00", due_days_ago=1),
            _invoice("Ancient", "10.00", due_days_ago=9),
        ]
        assert [i["customer_name"] for i in detect_unpaid_invoices(orders, now=NOW)] == [
            "Ancient",
            "Recent",
        ]


class TestStoreBackedTools:
    def teardown_method(self):
        clear_followups_context()

    def test_find_tools_read_the_store(self):
        convs = [_thread("Q", last_dir=MessageDirection.OUTBOUND, hours_ago=200)]
        orders = [_invoice("Owes", "99.00", due_days_ago=3)]
        set_followups_context(convs, orders)
        # quiet_after_hours small enough that the 200h-old thread always qualifies.
        assert any(t["customer_name"] == "Q" for t in find_quiet_threads(quiet_after_hours=24))
        assert any(i["customer_name"] == "Owes" for i in find_unpaid_invoices())

    def test_empty_store_returns_empty(self):
        clear_followups_context()
        assert find_quiet_threads() == []
        assert find_unpaid_invoices() == []


class TestDemoFollowupsSeed:
    def test_demo_seed_has_quiet_threads_and_one_unpaid_invoice(self):
        conversations, orders = create_demo_followups(NOW)
        quiet = detect_quiet_threads(conversations, now=NOW, quiet_after_hours=24)
        unpaid = detect_unpaid_invoices(orders, now=NOW)
        # Two quiet threads surface; the fresh (1h) control does not.
        assert len(quiet) == 2
        assert "Leo T." not in [t["customer_name"] for t in quiet]
        # One overdue invoice surfaces; the paid control does not.
        assert len(unpaid) == 1
        assert unpaid[0]["customer_name"] == "Marcus B."
        assert unpaid[0]["amount"] == "48.00"
