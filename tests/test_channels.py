"""Tests for the Wave 1 channel connectors (Instagram + WhatsApp).

Covers the connector seam (inbound normalization, signature verification,
outbound send shape), the encrypted token vault, the WhatsApp 24-hour service
window, the OAuth state binding, multi-tenant isolation, and — most importantly
— that outbound only ever happens on the approval path, never from an agent.
"""

import base64
import hashlib
import hmac
import uuid

import pytest
from fastapi.testclient import TestClient

from asili_agents.api import main as main_module
from asili_agents.api.main import app
from asili_agents.data.channel_store import InMemoryChannelStore
from asili_agents.data.models import (
    ChannelConnection,
    ChannelStatus,
    Conversation,
    ConversationStatus,
)
from asili_agents.integrations.channels.base import NormalizedInbound, SendOutcome
from asili_agents.integrations.channels.instagram import INSTAGRAM_SCOPES, InstagramChannel
from asili_agents.integrations.channels.meta_common import (
    META_SIGNATURE_HEADER,
    verify_meta_signature,
)
from asili_agents.integrations.channels.telegram import TelegramChannel
from asili_agents.integrations.channels.whatsapp import (
    WhatsAppChannel,
    within_service_window,
)
from asili_agents.integrations.secrets import TokenVault, TokenVaultError
from asili_agents.runner import RunResult


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _ok_run(*_args, **_kwargs):
    async def _run(runner, message, **kwargs):
        return RunResult(
            steps=[],
            draft="Yes, in stock. Want me to set one aside?",
            draft_sources=["stock"],
            facts={},
            raw_events=[],
            success=True,
        )

    return _run


# ── Fakes ────────────────────────────────────────────────────────────────────


class FakeResp:
    def __init__(self, status_code: int = 200, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = b"{}"

    def json(self) -> dict:
        return self._payload


class FakeAsyncClient:
    """Stand-in for httpx.AsyncClient that records the single POST it receives."""

    calls: list[dict] = []

    def __init__(self, resp: FakeResp) -> None:
        self._resp = resp

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *_a) -> bool:
        return False

    async def post(self, url, **kwargs) -> FakeResp:
        FakeAsyncClient.calls.append({"url": url, **kwargs})
        return self._resp


class FakeChannel:
    """Connector double: controllable signature, fixed inbound, records sends."""

    def __init__(self, platform: str, inbounds: list[NormalizedInbound]) -> None:
        self.platform = platform
        self._inbounds = inbounds
        self.sends: list[tuple[str, str, str]] = []
        self.verify_ok = True

    def verify_signature(self, raw_body: bytes, headers) -> bool:
        return self.verify_ok

    def parse_inbound(self, payload: dict) -> list[NormalizedInbound]:
        return list(self._inbounds)

    async def send(self, *, access_token: str, recipient_id: str, text: str) -> SendOutcome:
        self.sends.append((access_token, recipient_id, text))
        return SendOutcome(success=True, message_id="m_out")


# ── TokenVault ─────────────────────────────────────────────────────────────────


class TestTokenVault:
    def test_round_trip(self):
        vault = TokenVault(TokenVault.generate_key_b64())
        blob = vault.encrypt("super-secret-token")
        assert blob != "super-secret-token"
        assert vault.decrypt(blob) == "super-secret-token"

    def test_ciphertext_is_non_deterministic(self):
        vault = TokenVault(TokenVault.generate_key_b64())
        assert vault.encrypt("x") != vault.encrypt("x")  # fresh nonce each time

    def test_tamper_is_rejected(self):
        vault = TokenVault(TokenVault.generate_key_b64())
        blob = vault.encrypt("token")
        raw = bytearray(base64.b64decode(blob))
        raw[-1] ^= 0x01  # flip a bit in the tag/ciphertext
        tampered = base64.b64encode(bytes(raw)).decode()
        with pytest.raises(TokenVaultError):
            vault.decrypt(tampered)

    def test_wrong_key_cannot_decrypt(self):
        a = TokenVault(TokenVault.generate_key_b64())
        b = TokenVault(TokenVault.generate_key_b64())
        with pytest.raises(TokenVaultError):
            b.decrypt(a.encrypt("token"))

    def test_key_length_validated(self):
        short = base64.b64encode(b"too-short").decode()
        with pytest.raises(TokenVaultError):
            TokenVault(short)

    def test_bad_base64_key_rejected(self):
        with pytest.raises(TokenVaultError):
            TokenVault("not!base64!!")


# ── Meta signature verification ─────────────────────────────────────────────────


class TestMetaSignature:
    def _sig(self, secret: str, body: bytes) -> str:
        return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    def test_valid_signature_passes(self):
        body = b'{"object":"instagram"}'
        headers = {META_SIGNATURE_HEADER: self._sig("appsecret", body)}
        assert verify_meta_signature(body, headers, "appsecret") is True

    def test_wrong_signature_fails(self):
        body = b'{"object":"instagram"}'
        headers = {META_SIGNATURE_HEADER: self._sig("other", body)}
        assert verify_meta_signature(body, headers, "appsecret") is False

    def test_missing_header_fails(self):
        assert verify_meta_signature(b"{}", {}, "appsecret") is False

    def test_no_secret_fails_closed(self):
        body = b"{}"
        headers = {META_SIGNATURE_HEADER: self._sig("appsecret", body)}
        assert verify_meta_signature(body, headers, None) is False


# ── Instagram connector ─────────────────────────────────────────────────────────


class TestInstagramConnector:
    def test_scopes_are_instagram_login(self):
        assert "instagram_business_basic" in INSTAGRAM_SCOPES
        assert "instagram_business_manage_messages" in INSTAGRAM_SCOPES

    def test_parse_inbound_normalizes(self):
        ig = InstagramChannel(app_secret="s")
        payload = {
            "entry": [
                {
                    "messaging": [
                        {
                            "sender": {"id": "CUSTOMER_IGSID"},
                            "recipient": {"id": "SELLER_IG_ID"},
                            "message": {"mid": "mid_1", "text": "do you have the green tea?"},
                        }
                    ]
                }
            ]
        }
        out = ig.parse_inbound(payload)
        assert len(out) == 1
        msg = out[0]
        assert msg.recipient_account_id == "SELLER_IG_ID"  # routes to the seller
        assert msg.external_thread_id == "CUSTOMER_IGSID"  # reply target
        assert msg.text == "do you have the green tea?"
        assert msg.message_id == "mid_1"

    def test_parse_inbound_skips_echoes(self):
        ig = InstagramChannel(app_secret="s")
        payload = {
            "entry": [
                {
                    "messaging": [
                        {
                            "sender": {"id": "SELLER_IG_ID"},
                            "recipient": {"id": "CUSTOMER_IGSID"},
                            "message": {"is_echo": True, "text": "our own reply"},
                        }
                    ]
                }
            ]
        }
        assert ig.parse_inbound(payload) == []

    @pytest.mark.asyncio
    async def test_send_shape(self, monkeypatch):
        FakeAsyncClient.calls = []
        import asili_agents.integrations.channels.instagram as ig_mod

        monkeypatch.setattr(
            ig_mod.httpx,
            "AsyncClient",
            lambda **kw: FakeAsyncClient(FakeResp(200, {"message_id": "out_1"})),
        )
        ig = InstagramChannel(app_secret="s")
        outcome = await ig.send(access_token="TOK", recipient_id="CUSTOMER_IGSID", text="hi")
        assert outcome.success is True
        assert outcome.message_id == "out_1"
        call = FakeAsyncClient.calls[-1]
        assert call["url"].endswith("/me/messages")
        assert call["params"]["access_token"] == "TOK"
        assert call["json"]["recipient"]["id"] == "CUSTOMER_IGSID"
        assert call["json"]["message"]["text"] == "hi"

    @pytest.mark.asyncio
    async def test_send_surfaces_graph_error(self, monkeypatch):
        import asili_agents.integrations.channels.instagram as ig_mod

        monkeypatch.setattr(
            ig_mod.httpx,
            "AsyncClient",
            lambda **kw: FakeAsyncClient(FakeResp(400, {"error": {"message": "bad token"}})),
        )
        ig = InstagramChannel(app_secret="s")
        outcome = await ig.send(access_token="TOK", recipient_id="x", text="hi")
        assert outcome.success is False
        assert "bad token" in (outcome.error or "")


# ── WhatsApp connector ──────────────────────────────────────────────────────────


class TestWhatsAppConnector:
    def test_within_service_window(self):
        from datetime import UTC, datetime, timedelta

        now = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
        assert within_service_window(now - timedelta(hours=1), now) is True
        assert within_service_window(now - timedelta(hours=23, minutes=59), now) is True
        assert within_service_window(now - timedelta(hours=25), now) is False
        assert within_service_window(None, now) is False

    def test_parse_inbound_normalizes(self):
        wa = WhatsAppChannel(app_secret="s")
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": "PNID_123"},
                                "contacts": [
                                    {"wa_id": "255700000001", "profile": {"name": "Amina"}}
                                ],
                                "messages": [
                                    {
                                        "id": "wamid_1",
                                        "from": "255700000001",
                                        "type": "text",
                                        "text": {"body": "is it available?"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }
        out = wa.parse_inbound(payload)
        assert len(out) == 1
        msg = out[0]
        assert msg.recipient_account_id == "PNID_123"  # seller's number id
        assert msg.external_thread_id == "255700000001"  # customer wa_id
        assert msg.sender_name == "Amina"
        assert msg.text == "is it available?"

    def test_parse_inbound_skips_non_text(self):
        wa = WhatsAppChannel(app_secret="s")
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": "PNID"},
                                "messages": [{"id": "x", "from": "1", "type": "image"}],
                            }
                        }
                    ]
                }
            ]
        }
        assert wa.parse_inbound(payload) == []

    @pytest.mark.asyncio
    async def test_send_inert_until_bsp_live(self):
        wa = WhatsAppChannel(app_secret="s", live=False)
        outcome = await wa.send(access_token="TOK", recipient_id="PNID:255700", text="hi")
        assert outcome.success is False
        assert "not configured" in (outcome.error or "").lower()

    @pytest.mark.asyncio
    async def test_send_shape_when_live(self, monkeypatch):
        FakeAsyncClient.calls = []
        import asili_agents.integrations.channels.whatsapp as wa_mod

        monkeypatch.setattr(
            wa_mod.httpx,
            "AsyncClient",
            lambda **kw: FakeAsyncClient(FakeResp(200, {"messages": [{"id": "wamid_out"}]})),
        )
        wa = WhatsAppChannel(app_secret="s", live=True)
        outcome = await wa.send(access_token="TOK", recipient_id="PNID_123:255700000001", text="hi")
        assert outcome.success is True
        assert outcome.message_id == "wamid_out"
        call = FakeAsyncClient.calls[-1]
        assert "/PNID_123/messages" in call["url"]
        assert call["headers"]["Authorization"] == "Bearer TOK"
        assert call["json"]["to"] == "255700000001"
        assert call["json"]["text"]["body"] == "hi"


# ── Telegram connector (dev/secondary channel) ──────────────────────────────────


class TestTelegramConnector:
    def test_verify_signature(self):
        tg = TelegramChannel(webhook_secret="topsecret")
        assert tg.verify_signature(b"{}", {"x-telegram-bot-api-secret-token": "topsecret"}) is True
        assert tg.verify_signature(b"{}", {"x-telegram-bot-api-secret-token": "nope"}) is False

    def test_verify_fails_closed_without_secret(self):
        tg = TelegramChannel(webhook_secret=None)
        assert tg.verify_signature(b"{}", {"x-telegram-bot-api-secret-token": "anything"}) is False


# ── OAuth state binding ─────────────────────────────────────────────────────────


class TestOAuthState:
    def test_sign_verify_round_trip(self, monkeypatch):
        monkeypatch.setattr(
            main_module.get_settings(), "oauth_state_secret", "state-secret", raising=False
        )
        state = main_module._sign_oauth_state("seller-123")
        assert main_module._verify_oauth_state(state) == "seller-123"

    def test_forged_seller_rejected(self, monkeypatch):
        monkeypatch.setattr(
            main_module.get_settings(), "oauth_state_secret", "state-secret", raising=False
        )
        state = main_module._sign_oauth_state("seller-123")
        raw = base64.urlsafe_b64decode(state + "===").decode()
        _seller, nonce, sig = raw.rsplit("|", 2)
        # Reuse a legitimate signature but claim a different seller -> must fail.
        forged = (
            base64.urlsafe_b64encode(f"seller-EVIL|{nonce}|{sig}".encode()).decode().rstrip("=")
        )
        assert main_module._verify_oauth_state(forged) is None

    def test_garbage_state_rejected(self):
        assert main_module._verify_oauth_state("totally-not-valid") is None


# ── Inbound webhook: routing, isolation, outbound-only-on-approval ──────────────


class TestChannelInboundIsolation:
    def _two_seller_store(self) -> InMemoryChannelStore:
        store = InMemoryChannelStore()
        store.upsert(
            ChannelConnection(
                seller_id="sellerA",
                platform="instagram",
                external_account_id="IG_ACCOUNT_A",
                status=ChannelStatus.CONNECTED,
            )
        )
        store.upsert(
            ChannelConnection(
                seller_id="sellerB",
                platform="instagram",
                external_account_id="IG_ACCOUNT_B",
                status=ChannelStatus.CONNECTED,
            )
        )
        return store

    def test_inbound_routes_to_owning_seller_only(self, client, monkeypatch):
        inb = NormalizedInbound(
            recipient_account_id="IG_ACCOUNT_A",
            external_thread_id="cust_1",
            sender_name="Customer",
            text="do you have the tea?",
            message_id="mid_unique_1",
        )
        fake = FakeChannel("instagram", [inb])
        monkeypatch.setitem(main_module._state, "channels", {"instagram": fake})
        monkeypatch.setitem(main_module._state, "channel_store", self._two_seller_store())
        monkeypatch.setattr(main_module, "create_runner", lambda *a, **k: object())
        monkeypatch.setattr(main_module, "run_agent_async", _ok_run())

        r = client.post("/api/instagram/webhook", json={"object": "instagram"})
        assert r.status_code == 200, r.text
        assert r.json()["handled"] == 1

        pending = main_module._state["pending_drafts"]
        assert "sellerA:instagram:cust_1" in pending
        assert not any(k.startswith("sellerB:") for k in pending)
        # Outbound NEVER fires on inbound — the draft only holds at the gate.
        assert fake.sends == []

    def test_inbound_for_unmapped_account_is_ignored(self, client, monkeypatch):
        inb = NormalizedInbound(
            recipient_account_id="IG_ACCOUNT_UNKNOWN",
            external_thread_id="cust_x",
            sender_name="Customer",
            text="hello?",
            message_id="mid_unique_2",
        )
        fake = FakeChannel("instagram", [inb])
        monkeypatch.setitem(main_module._state, "channels", {"instagram": fake})
        monkeypatch.setitem(main_module._state, "channel_store", self._two_seller_store())
        monkeypatch.setattr(main_module, "create_runner", lambda *a, **k: object())
        monkeypatch.setattr(main_module, "run_agent_async", _ok_run())

        r = client.post("/api/instagram/webhook", json={"object": "instagram"})
        assert r.status_code == 200
        assert r.json()["handled"] == 0
        assert main_module._state["pending_drafts"] == {} or not any(
            "cust_x" in k for k in main_module._state["pending_drafts"]
        )

    def test_bad_signature_rejected(self, client, monkeypatch):
        fake = FakeChannel("instagram", [])
        fake.verify_ok = False
        monkeypatch.setitem(main_module._state, "channels", {"instagram": fake})
        r = client.post("/api/instagram/webhook", json={"object": "instagram"})
        assert r.status_code == 401

    def test_whatsapp_inbound_encodes_send_recipient(self, client, monkeypatch):
        inb = NormalizedInbound(
            recipient_account_id="PNID_999",
            external_thread_id="255700000009",
            sender_name="Amina",
            text="is it available?",
            message_id="wamid_unique_1",
        )
        fake = FakeChannel("whatsapp", [inb])
        monkeypatch.setitem(main_module._state, "channels", {"whatsapp": fake})
        store = InMemoryChannelStore()
        store.upsert(
            ChannelConnection(
                seller_id="sellerW",
                platform="whatsapp",
                external_account_id="PNID_999",
                status=ChannelStatus.CONNECTED,
            )
        )
        monkeypatch.setitem(main_module._state, "channel_store", store)
        monkeypatch.setattr(main_module, "create_runner", lambda *a, **k: object())
        monkeypatch.setattr(main_module, "run_agent_async", _ok_run())

        r = client.post("/api/whatsapp/webhook", json={"object": "whatsapp_business_account"})
        assert r.status_code == 200
        cid = "sellerW:whatsapp:255700000009"
        draft = main_module._state["pending_drafts"][cid]
        # WhatsApp send needs "phone_number_id:to_wa_id".
        assert draft["recipient_id"] == "PNID_999:255700000009"
        assert draft["seller_id"] == "sellerW"

    def test_idempotent_redelivery_skipped(self, client, monkeypatch):
        inb = NormalizedInbound(
            recipient_account_id="IG_ACCOUNT_A",
            external_thread_id="cust_dupe",
            sender_name="Customer",
            text="hi",
            message_id="mid_dupe_1",
        )
        fake = FakeChannel("instagram", [inb])
        monkeypatch.setitem(main_module._state, "channels", {"instagram": fake})
        monkeypatch.setitem(main_module._state, "channel_store", self._two_seller_store())
        runs = {"n": 0}

        async def counting_run(runner, message, **kwargs):
            runs["n"] += 1
            return RunResult(
                steps=[], draft="ok", draft_sources=[], facts={}, raw_events=[], success=True
            )

        monkeypatch.setattr(main_module, "create_runner", lambda *a, **k: object())
        monkeypatch.setattr(main_module, "run_agent_async", counting_run)

        client.post("/api/instagram/webhook", json={"object": "instagram"})
        client.post("/api/instagram/webhook", json={"object": "instagram"})
        # The agent (a billable run) fires once; the redelivery is deduped.
        assert runs["n"] == 1


# ── Approve path: connector send fires only here, with the seller's token ───────


class TestApproveSendsViaConnector:
    def test_approve_decrypts_token_and_sends(self, client, monkeypatch):
        vault = TokenVault(TokenVault.generate_key_b64())
        fake = FakeChannel("instagram", [])
        monkeypatch.setitem(main_module._state, "channels", {"instagram": fake})
        monkeypatch.setitem(main_module._state, "token_vault", vault)

        store = InMemoryChannelStore()
        store.upsert(
            ChannelConnection(
                seller_id="sellerA",
                platform="instagram",
                external_account_id="IG_ACCOUNT_A",
                encrypted_token=vault.encrypt("SELLER_A_TOKEN"),
                status=ChannelStatus.CONNECTED,
            )
        )
        monkeypatch.setitem(main_module._state, "channel_store", store)

        conv = Conversation(
            seller_id=uuid.uuid4(),
            customer_name="Customer",
            customer_initials="C",
            channel="Instagram DM",
            status=ConversationStatus.AWAITING_REPLY,
        )
        cid = "sellerA:instagram:cust_1"
        monkeypatch.setitem(main_module._state["conversations"], cid, conv)
        monkeypatch.setitem(
            main_module._state["pending_drafts"],
            cid,
            {
                "draft_id": "d",
                "body": "Yes, in stock!",
                "sources": [],
                "status": "pending",
                "channel": "instagram",
                "recipient_id": "cust_1",
                "seller_id": "sellerA",
            },
        )

        r = client.post("/api/approve", json={"conversation_id": cid, "action": "approve"})
        assert r.status_code == 200, r.text
        # Decrypted the seller's own token and sent to the customer thread.
        assert fake.sends == [("SELLER_A_TOKEN", "cust_1", "Yes, in stock!")]

    def test_approve_without_token_does_not_send(self, client, monkeypatch):
        fake = FakeChannel("instagram", [])
        monkeypatch.setitem(main_module._state, "channels", {"instagram": fake})
        monkeypatch.setitem(main_module._state, "token_vault", None)
        monkeypatch.setitem(main_module._state, "channel_store", InMemoryChannelStore())

        conv = Conversation(
            seller_id=uuid.uuid4(),
            customer_name="Customer",
            customer_initials="C",
            channel="Instagram DM",
            status=ConversationStatus.AWAITING_REPLY,
        )
        cid = "sellerNo:instagram:cust_2"
        monkeypatch.setitem(main_module._state["conversations"], cid, conv)
        monkeypatch.setitem(
            main_module._state["pending_drafts"],
            cid,
            {
                "draft_id": "d",
                "body": "Yes!",
                "sources": [],
                "status": "pending",
                "channel": "instagram",
                "recipient_id": "cust_2",
                "seller_id": "sellerNo",
            },
        )

        r = client.post("/api/approve", json={"conversation_id": cid, "action": "approve"})
        # The approval still succeeds and logs the message; it just can't deliver.
        assert r.status_code == 200, r.text
        assert fake.sends == []


# ── /api/channels: per-seller status, header-scoped ─────────────────────────────


class TestChannelsStatus:
    def test_default_seller_not_connected(self, client, monkeypatch):
        monkeypatch.setitem(main_module._state, "channel_store", InMemoryChannelStore())
        body = client.get("/api/channels").json()
        assert body["seller_id"] == "demo"
        assert body["channels"]["instagram"]["status"] == "not_connected"
        assert body["channels"]["whatsapp"]["status"] == "not_connected"

    def test_connected_seller_status_by_header(self, client, monkeypatch):
        store = InMemoryChannelStore()
        store.upsert(
            ChannelConnection(
                seller_id="sellerA",
                platform="instagram",
                external_account_id="IG_ACCOUNT_A",
                external_handle="@shopA",
                status=ChannelStatus.CONNECTED,
            )
        )
        monkeypatch.setitem(main_module._state, "channel_store", store)
        body = client.get("/api/channels", headers={"x-asili-seller-id": "sellerA"}).json()
        assert body["seller_id"] == "sellerA"
        assert body["channels"]["instagram"]["status"] == "connected"
        assert body["channels"]["instagram"]["handle"] == "@shopA"
        # Isolation: a different seller sees nothing of sellerA's connection.
        other = client.get("/api/channels", headers={"x-asili-seller-id": "sellerB"}).json()
        assert other["channels"]["instagram"]["status"] == "not_connected"
