"""Telegram connector — kept as a dev/secondary channel behind the seam.

Telegram is no longer the primary path (sellers live on Instagram/WhatsApp), but
it stays available because it's the one channel that can exercise the full
inbound -> draft -> approve -> real send loop without Meta credentials. It wraps
the existing TelegramClient + parse_update.
"""

from __future__ import annotations

import hmac
from collections.abc import Mapping

from asili_agents.integrations.channels.base import NormalizedInbound, SendOutcome
from asili_agents.integrations.telegram import SECRET_HEADER, TelegramClient, parse_update


class TelegramChannel:
    platform = "telegram"

    def __init__(self, *, webhook_secret: str | None, timeout: float = 15.0) -> None:
        self._webhook_secret = webhook_secret
        self._timeout = timeout

    def verify_signature(self, raw_body: bytes, headers: Mapping[str, str]) -> bool:
        # Telegram echoes the configured secret in this header. Fail closed.
        secret = self._webhook_secret
        if not secret:
            return False
        provided = headers.get(SECRET_HEADER) or headers.get("X-Telegram-Bot-Api-Secret-Token")
        if not provided:
            return False
        return hmac.compare_digest(provided, secret)

    def parse_inbound(self, payload: dict) -> list[NormalizedInbound]:
        msg = parse_update(payload)
        if msg is None or not msg.text:
            return []
        return [
            NormalizedInbound(
                recipient_account_id="telegram",  # single dev bot; not multi-account
                external_thread_id=msg.chat_id,
                sender_name=msg.sender_name,
                text=msg.text,
                message_id=str(msg.message_id) if msg.message_id is not None else None,
            )
        ]

    async def send(self, *, access_token: str, recipient_id: str, text: str) -> SendOutcome:
        try:
            client = TelegramClient(access_token, timeout=self._timeout)
            resp = await client.send_message(recipient_id, text)
            if not resp.get("ok", False):
                return SendOutcome(
                    success=False, error=str(resp.get("description") or "send failed")
                )
            result = resp.get("result") or {}
            mid = result.get("message_id")
            return SendOutcome(success=True, message_id=str(mid) if mid is not None else None)
        except Exception as exc:  # noqa: BLE001
            return SendOutcome(success=False, error=str(exc))
