"""WhatsApp connector (Cloud API via a BSP), behind the channel seam.

Built now, live BSP deferred: the inbound normalization, Meta signature
verification, the 24-hour service-window rule, and the Cloud-API-shaped outbound
send are all here behind the ``Channel`` interface. Until a BSP account + creds
exist the connector runs in ``live=False`` mode and ``send`` is inert (returns a
clear not-configured error) so nothing is half-wired.

Rules encoded: a customer message opens a 24-hour service window in which a
free-form reply is allowed; outside it, a send requires a pre-approved template
and prior opt-in (not yet implemented — flagged for the BSP wave).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import httpx

from asili_agents.integrations.channels.base import NormalizedInbound, SendOutcome
from asili_agents.integrations.channels.meta_common import verify_meta_signature

SERVICE_WINDOW = timedelta(hours=24)


def within_service_window(last_inbound_at: datetime | None, now: datetime) -> bool:
    """True if a free-form reply is allowed (within 24h of the last inbound)."""
    if last_inbound_at is None:
        return False
    return (now - last_inbound_at) <= SERVICE_WINDOW


class WhatsAppChannel:
    platform = "whatsapp"

    def __init__(
        self,
        *,
        app_secret: str | None,
        live: bool = False,
        graph_base: str = "https://graph.facebook.com",
        api_version: str = "v21.0",
        timeout: float = 15.0,
    ) -> None:
        self._app_secret = app_secret
        self._live = live
        self._graph_base = graph_base.rstrip("/")
        self._api_version = api_version
        self._timeout = timeout

    def verify_signature(self, raw_body: bytes, headers: Mapping[str, str]) -> bool:
        return verify_meta_signature(raw_body, headers, self._app_secret)

    def parse_inbound(self, payload: dict) -> list[NormalizedInbound]:
        out: list[NormalizedInbound] = []
        for entry in payload.get("entry", []) or []:
            for change in entry.get("changes", []) or []:
                value = change.get("value") or {}
                metadata = value.get("metadata") or {}
                recipient = metadata.get("phone_number_id")  # the seller's number
                names = {
                    c.get("wa_id"): ((c.get("profile") or {}).get("name") or "Customer")
                    for c in (value.get("contacts") or [])
                }
                for msg in value.get("messages", []) or []:
                    if msg.get("type") != "text":
                        continue
                    sender = msg.get("from")
                    text = (msg.get("text") or {}).get("body")
                    if not sender or not recipient or not text:
                        continue
                    out.append(
                        NormalizedInbound(
                            recipient_account_id=str(recipient),
                            external_thread_id=str(sender),
                            sender_name=names.get(sender, "Customer"),
                            text=str(text),
                            message_id=msg.get("id"),
                        )
                    )
        return out

    async def send(
        self,
        *,
        access_token: str,
        recipient_id: str,
        text: str,
        last_inbound_at: datetime | None = None,
    ) -> SendOutcome:
        # Inert until a BSP is wired: do not pretend to deliver.
        if not self._live:
            return SendOutcome(
                success=False,
                error="WhatsApp BSP not configured (connector built, live integration pending)",
            )
        # Free-form replies are allowed only inside the 24h service window. Outside
        # it, WhatsApp requires a pre-approved template + prior opt-in (BSP wave).
        # When the caller supplies the last inbound time we fast-fail locally
        # instead of paying a round-trip the Cloud API would reject anyway.
        if last_inbound_at is not None and not within_service_window(
            last_inbound_at, datetime.now(UTC)
        ):
            return SendOutcome(
                success=False,
                error="outside the 24h service window; an approved template + opt-in are required",
            )
        # recipient_id encodes "phone_number_id:to_wa_id" so a single signature
        # serves every channel; WhatsApp needs the sender's own number id.
        phone_number_id, _, to = recipient_id.partition(":")
        url = f"{self._graph_base}/{self._api_version}/{phone_number_id}/messages"
        body = {
            "messaging_product": "whatsapp",
            "to": to or recipient_id,
            "type": "text",
            "text": {"body": text},
        }
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=body, headers=headers)
                data = resp.json() if resp.content else {}
            if resp.status_code >= 400 or "error" in data:
                err = (data.get("error") or {}).get("message") or f"HTTP {resp.status_code}"
                return SendOutcome(success=False, error=str(err))
            msg_id = ((data.get("messages") or [{}])[0]).get("id")
            return SendOutcome(success=True, message_id=msg_id)
        except Exception as exc:  # noqa: BLE001
            return SendOutcome(success=False, error=str(exc))
