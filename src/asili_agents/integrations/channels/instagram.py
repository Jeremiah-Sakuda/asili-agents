"""Instagram connector (Instagram-Login messaging path).

Reactive by design: Instagram messaging is user-initiated, with a 24-hour
standard reply window (extendable to 7 days with the human-agent tag for genuine
support). There is no compliant cold outbound, so this connector only ever
replies to a customer who messaged first, and only after the seller approves.

OAuth (code exchange) lives in the API layer; this class is the transport:
verify inbound, normalize it, and send an approved reply via the IG Graph API
using the seller's own access token.
"""

from __future__ import annotations

from collections.abc import Mapping

import httpx

from asili_agents.integrations.channels.base import NormalizedInbound, SendOutcome
from asili_agents.integrations.channels.meta_common import verify_meta_signature

# Permissions the seller grants at connect time (Instagram Login, no FB Page).
INSTAGRAM_SCOPES = "instagram_business_basic,instagram_business_manage_messages"


class InstagramChannel:
    platform = "instagram"

    def __init__(
        self,
        *,
        app_secret: str | None,
        graph_base: str = "https://graph.instagram.com",
        api_version: str = "v21.0",
        timeout: float = 15.0,
    ) -> None:
        self._app_secret = app_secret
        self._graph_base = graph_base.rstrip("/")
        self._api_version = api_version
        self._timeout = timeout

    def verify_signature(self, raw_body: bytes, headers: Mapping[str, str]) -> bool:
        return verify_meta_signature(raw_body, headers, self._app_secret)

    def parse_inbound(self, payload: dict) -> list[NormalizedInbound]:
        out: list[NormalizedInbound] = []
        for entry in payload.get("entry", []) or []:
            for event in entry.get("messaging", []) or []:
                message = event.get("message") or {}
                # Skip echoes (our own sends) and non-text events.
                if message.get("is_echo") or not message.get("text"):
                    continue
                sender = (event.get("sender") or {}).get("id")
                recipient = (event.get("recipient") or {}).get("id")
                if not sender or not recipient:
                    continue
                out.append(
                    NormalizedInbound(
                        recipient_account_id=str(recipient),
                        external_thread_id=str(sender),
                        sender_name="Customer",  # IG webhook carries no name; resolved later if needed
                        text=str(message.get("text")),
                        message_id=message.get("mid"),
                    )
                )
        return out

    async def send(self, *, access_token: str, recipient_id: str, text: str) -> SendOutcome:
        url = f"{self._graph_base}/{self._api_version}/me/messages"
        params = {"access_token": access_token}
        body = {"recipient": {"id": recipient_id}, "message": {"text": text}}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, params=params, json=body)
                data = resp.json() if resp.content else {}
            if resp.status_code >= 400 or "error" in data:
                err = (data.get("error") or {}).get("message") or f"HTTP {resp.status_code}"
                return SendOutcome(success=False, error=str(err))
            return SendOutcome(success=True, message_id=data.get("message_id"))
        except Exception as exc:  # noqa: BLE001 — never raise into the approve path
            return SendOutcome(success=False, error=str(exc))
