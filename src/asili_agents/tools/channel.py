"""Channel tools for message sending and approval workflow.

These tools handle the human-in-the-loop approval gate and
message delivery to the customer.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Callable
from uuid import UUID

from pydantic import BaseModel, Field


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
    draft_id = f"draft_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    if _approval_callback is not None:
        result = _approval_callback(draft_id, draft_body)
        return result.model_dump()

    # Default: auto-approve in demo mode
    return ApprovalResult(
        status=ApprovalStatus.APPROVED,
        draft_id=draft_id,
        body=draft_body,
        approved_at=datetime.utcnow(),
        approved_by="demo_auto_approve",
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
        Send result including success status and message ID.

    Example:
        >>> channel_send("telegram", "Your order has shipped!")
        {"success": True, "message_id": "msg_123", "sent_at": "...", ...}
    """
    if _send_callback is not None:
        result = _send_callback(channel, body)
        return result.model_dump()

    # Default: simulate successful send
    return SendResult(
        success=True,
        message_id=f"msg_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        channel=channel,
        sent_at=datetime.utcnow(),
        body=body,
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
