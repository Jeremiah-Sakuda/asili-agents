"""Channel tools for message sending and approval workflow.

These tools handle the human-in-the-loop approval gate and
message delivery to the customer.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from asili_agents.tools import autonomy
from asili_agents.tools.autonomy import AutonomyPolicy, AutonomyTier


class ApprovalStatus(str, Enum):
    """Status of an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"


class ApprovalResult(BaseModel):
    """Result from an approval request."""

    status: ApprovalStatus
    draft_id: str
    body: str
    edited_body: str | None = None
    approved_at: datetime | None = None
    approved_by: str | None = None


class SendResult(BaseModel):
    """Result from sending a message."""

    success: bool
    message_id: str | None = None
    channel: str
    sent_at: datetime
    body: str
    error: str | None = None


# Callback for approval workflow (set by the runtime)
_approval_callback: Callable[[str, str], ApprovalResult] | None = None
_send_callback: Callable[[str, str], SendResult] | None = None
# Opt-in auto-approve for non-interactive demos (e.g. the CLI). OFF by default so
# the gate FAILS CLOSED: with no approval callback wired, drafts stay PENDING and
# nothing is ever sent unsupervised.
_auto_approve_enabled: bool = False

# Active seller autonomy policy ("trust ladder"). None = fail closed: every
# decision holds for approval. When set + enabled, a low-risk, policy-allowed,
# structurally-safe decision executes at Tier 1 without per-action approval.
_autonomy_policy: AutonomyPolicy | None = None


def set_auto_approve(enabled: bool) -> None:
    """Enable auto-approval for non-interactive demos. Off by default (fail closed)."""
    global _auto_approve_enabled
    _auto_approve_enabled = enabled


def set_autonomy_policy(policy: AutonomyPolicy | None) -> None:
    """Set the active seller autonomy policy. None disables Tier-1 auto-execute."""
    global _autonomy_policy
    _autonomy_policy = policy


def set_approval_callback(callback: Callable[[str, str], ApprovalResult]) -> None:
    """Set the callback for handling approval requests.

    In a real deployment, this would integrate with the UI
    to show the draft and collect the seller's decision.

    Args:
        callback: Function that takes (draft_id, body) and returns ApprovalResult
    """
    global _approval_callback
    _approval_callback = callback


def set_send_callback(callback: Callable[[str, str], SendResult]) -> None:
    """Set the callback for sending messages.

    In a real deployment, this would integrate with Telegram
    or another messaging channel.

    Args:
        callback: Function that takes (channel, body) and returns SendResult
    """
    global _send_callback
    _send_callback = callback


def send_for_approval(
    draft_body: str,
    sources: list[str] | None = None,
    agent_name: str = "Messaging",
    *,
    intent: str | None = None,
    grounded: bool | None = None,
    margin_safe: bool | None = None,
) -> dict[str, Any]:
    """Submit a draft message for human approval before sending.

    This tool implements the human-in-the-loop pattern. The draft
    will be shown to the seller who can:
    - Approve: Send as-is
    - Edit: Modify and then send
    - Reject: Discard the draft

    NEVER send a message to a customer without going through
    this approval flow first.

    Args:
        draft_body: The proposed message to send to the customer.
        sources: List of data sources used to compose the message
            (e.g., ["Catalog · Purple Tea", "Stock · 6 tins"]).
        agent_name: Name of the agent that composed the draft.

    Returns:
        Approval result including:
        - status: "approved", "edited", or "rejected"
        - body: The final approved message (may be edited)

    Example:
        >>> send_for_approval(
        ...     "Yes, we have Purple Tea in stock!",
        ...     sources=["Catalog · Purple Tea", "Stock · 6 tins"]
        ... )
        {"status": "approved", "body": "Yes, we have Purple Tea in stock!", ...}
    """
    # Timestamp for human readability + a short random suffix so two drafts
    # composed in the same second can never collide on the same id.
    draft_id = f"draft_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"

    # Graduated autonomy: a low-risk, policy-allowed, structurally-safe decision
    # executes at Tier 1 WITHOUT per-action approval (this overrides the human
    # gate for exactly the class the seller opted in to). Everything else — and
    # everything when no policy is set — holds, preserving the fail-closed gate.
    resolved_intent = intent or autonomy.classify_intent(draft_body, sources, agent_name)
    grounded_signal = grounded if grounded is not None else bool(sources)
    tier = autonomy.decide_tier(
        _autonomy_policy, resolved_intent, grounded=grounded_signal, margin_safe=margin_safe
    )
    autonomy.record_decision(tier)
    if tier is AutonomyTier.AUTO:
        return ApprovalResult(
            status=ApprovalStatus.APPROVED,
            draft_id=draft_id,
            body=draft_body,
            approved_at=datetime.now(UTC),
            approved_by=f"tier1_autonomy:{resolved_intent}",
        ).model_dump()

    if _approval_callback is not None:
        result = _approval_callback(draft_id, draft_body)
        return result.model_dump()

    if _auto_approve_enabled:
        # Explicit opt-in only (e.g. the CLI demo).
        return ApprovalResult(
            status=ApprovalStatus.APPROVED,
            draft_id=draft_id,
            body=draft_body,
            approved_at=datetime.now(UTC),
            approved_by="auto_approve_demo",
        ).model_dump()

    # Fail closed: no callback and no explicit auto-approve -> hold as PENDING.
    # Nothing is sent to a customer without a real approval decision.
    return ApprovalResult(
        status=ApprovalStatus.PENDING,
        draft_id=draft_id,
        body=draft_body,
    ).model_dump()


def channel_send(
    channel: str,
    body: str,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """Send a message to the customer via the specified channel.

    This tool should only be called AFTER the message has been
    approved via send_for_approval.

    Args:
        channel: The communication channel (e.g., "telegram", "storefront_chat").
        body: The message body to send.
        conversation_id: Optional conversation ID for threading.

    Returns:
        Send result including success status and message ID. If no send callback
        is registered, this fails closed (``success=False`` with an ``error``)
        rather than simulating delivery.

    Example:
        >>> channel_send("telegram", "Your order has shipped!")  # callback wired
        {"success": True, "message_id": "msg_123", "sent_at": "...", ...}
    """
    if _send_callback is not None:
        result = _send_callback(channel, body)
        return result.model_dump()

    # Fail closed: with no real send callback wired, do NOT pretend the message
    # was delivered. The only legitimate outbound path is the approval flow
    # (POST /api/approve), which registers a real callback. Anything reaching
    # here without one must surface that nothing was sent — consistent with the
    # system's fail-closed posture — rather than simulate a successful send.
    return SendResult(
        success=False,
        message_id=None,
        channel=channel,
        sent_at=datetime.now(UTC),
        body=body,
        error="no send callback wired — message not delivered",
    ).model_dump()


def channel_receive() -> dict[str, Any] | None:
    """Receive the next pending message from any channel.

    This tool polls for new inbound messages. In a real deployment,
    this would be replaced by a webhook-based system.

    Returns:
        The next pending message, or None if no messages are waiting.
    """
    # In a real system, this would check a message queue
    # For now, return None (no pending messages)
    return None
