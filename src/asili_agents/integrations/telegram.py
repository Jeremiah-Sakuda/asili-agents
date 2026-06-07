"""Telegram Bot channel — inbound parsing + outbound delivery.

Reproduces the transport used by the main Asili app (Telegram Bot API over
HTTPS) for the seller-facing operations team. The agent's reply is NOT sent
directly from here: an inbound customer message becomes a *pending draft* that
the seller approves, and only an approved draft is delivered back to the
customer's chat (see ``api.main``). That keeps the human-approval gate intact.

API: https://api.telegram.org/bot<TOKEN>/<method>
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

TELEGRAM_API_BASE = "https://api.telegram.org/bot"
# Header Telegram echoes back when a webhook secret_token is configured.
SECRET_HEADER = "x-telegram-bot-api-secret-token"


@dataclass
class InboundTelegramMessage:
    """A normalized inbound Telegram text message."""

    chat_id: str
    text: str
    message_id: int | None
    sender_name: str


def parse_update(payload: dict[str, Any]) -> InboundTelegramMessage | None:
    """Extract a normalized text message from a Telegram ``Update``.

    Returns None for updates we don't handle (no message, non-text, callbacks).
    """
    message = payload.get("message") or payload.get("edited_message")
    if not isinstance(message, dict):
        return None

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return None

    sender = message.get("from") or {}
    name = (
        " ".join(p for p in (sender.get("first_name"), sender.get("last_name")) if p)
        or sender.get("username")
        or "Customer"
    )
    return InboundTelegramMessage(
        chat_id=str(chat_id),
        text=message.get("text") or "",
        message_id=message.get("message_id"),
        sender_name=name,
    )


def initials_of(name: str) -> str:
    """Two-letter avatar initials for a display name."""
    parts = [p for p in name.split() if p]
    if not parts:
        return "C"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


class TelegramClient:
    """Thin async client over the Telegram Bot API (uses httpx)."""

    def __init__(self, bot_token: str, *, timeout: float = 15.0) -> None:
        self._token = bot_token
        self._timeout = timeout

    def _url(self, method: str) -> str:
        return f"{TELEGRAM_API_BASE}{self._token}/{method}"

    async def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(self._url(method), json=params)
            data: dict[str, Any] = response.json()
            return data

    async def send_message(
        self,
        chat_id: str,
        text: str,
        *,
        parse_mode: str | None = "Markdown",
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a text message. Returns the Telegram API response dict."""
        params: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode:
            params["parse_mode"] = parse_mode
        if reply_markup is not None:
            params["reply_markup"] = reply_markup
        return await self._call("sendMessage", params)

    async def send_chat_action(self, chat_id: str, action: str = "typing") -> dict[str, Any]:
        """Show a status (e.g. 'typing') to the customer."""
        return await self._call("sendChatAction", {"chat_id": chat_id, "action": action})

    async def set_webhook(self, url: str, *, secret_token: str | None = None) -> dict[str, Any]:
        """Register the webhook URL with Telegram (optionally with a secret token)."""
        params: dict[str, Any] = {"url": url}
        if secret_token:
            params["secret_token"] = secret_token
        return await self._call("setWebhook", params)
