"""Channel connector seam.

One ``Channel`` interface, with Instagram / WhatsApp / Telegram behind it, so the
agent layer and the approval gate stay channel-agnostic. Connectors are pure
transports: they normalize inbound platform payloads into ``NormalizedInbound``
(which the API turns into the existing Conversation/Message model, scoped per
seller), verify inbound authenticity, and — ONLY when the approval API calls
``send`` — deliver an approved reply as the seller. No connector is ever handed
to an agent; the only outbound path is the human-approved ``/api/approve``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class NormalizedInbound:
    """A platform-agnostic inbound customer message.

    ``recipient_account_id`` identifies the SELLER's account that received the
    message (Instagram business id, WhatsApp phone-number id, or the Telegram bot
    id), used to resolve which seller's ChannelConnection this belongs to.
    ``external_thread_id`` identifies the CUSTOMER conversation on the platform.
    """

    recipient_account_id: str
    external_thread_id: str
    sender_name: str
    text: str
    message_id: str | None = None


@dataclass
class SendOutcome:
    """Result of delivering an approved reply through a channel."""

    success: bool
    message_id: str | None = None
    error: str | None = None


@runtime_checkable
class Channel(Protocol):
    """A messaging-channel connector. Stateless w.r.t. sellers: per-seller
    credentials (the access token, recipient id) are passed in at call time so a
    single connector instance serves every tenant."""

    platform: str

    def verify_signature(self, raw_body: bytes, headers: Mapping[str, str]) -> bool:
        """Return True iff the inbound webhook is authentic for this channel.

        Connectors with no signing secret configured MUST fail closed (return
        False) rather than accept unverified inbound.
        """
        ...

    def parse_inbound(self, payload: dict) -> list[NormalizedInbound]:
        """Normalize a webhook body into zero or more inbound messages.

        Returns an empty list for payloads we don't handle (status callbacks,
        echoes, non-text events).
        """
        ...

    async def send(self, *, access_token: str, recipient_id: str, text: str) -> SendOutcome:
        """Deliver an approved reply to the customer as the seller.

        Called ONLY from the approval API path, never by an agent.
        """
        ...
