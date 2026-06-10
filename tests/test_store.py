"""Tests for the durable conversation/pending store."""

import uuid

from asili_agents.data.models import Conversation, ConversationStatus, MessageDirection
from asili_agents.data.store import InMemoryStore, TenantScopedStore


def _conv(name: str = "Amina") -> Conversation:
    c = Conversation(
        seller_id=uuid.uuid4(),
        customer_name=name,
        customer_initials="A",
        channel="Telegram",
        status=ConversationStatus.AWAITING_REPLY,
    )
    c.add_message(direction=MessageDirection.INBOUND, sender_name=name, body="purple tea?")
    return c


class TestInMemoryStore:
    def test_conversation_save_get_list(self):
        store = InMemoryStore({}, {})
        store.save_conversation("tg:1", _conv())
        got = store.get_conversation("tg:1")
        assert got is not None
        assert got.customer_name == "Amina"
        assert [cid for cid, _ in store.list_conversations()] == ["tg:1"]

    def test_pending_lifecycle(self):
        store = InMemoryStore({}, {})
        assert store.has_pending("tg:1") is False
        store.set_pending("tg:1", {"body": "Yes", "channel": "telegram"})
        assert store.has_pending("tg:1") is True
        pending = store.get_pending("tg:1")
        assert pending is not None and pending["body"] == "Yes"
        store.delete_pending("tg:1")
        assert store.get_pending("tg:1") is None

    def test_clear(self):
        store = InMemoryStore({}, {})
        store.save_conversation("a", _conv())
        store.set_pending("a", {"body": "x"})
        store.clear()
        assert store.list_conversations() == []
        assert store.has_pending("a") is False


class TestSerializationRoundTrip:
    """MongoStore persists via model_dump(mode='json') -> model_validate."""

    def test_conversation_json_roundtrip(self):
        original = _conv()
        restored = Conversation.model_validate(original.model_dump(mode="json"))
        assert restored.customer_name == original.customer_name
        assert restored.channel == "Telegram"
        assert len(restored.messages) == 1
        assert restored.messages[0].body == "purple tea?"
        assert restored.messages[0].direction == MessageDirection.INBOUND


class TestTenantScopedStore:
    """Thin multi-tenancy: two sellers share one backend with zero collision."""

    def test_same_conversation_id_does_not_collide(self):
        backend = InMemoryStore({}, {})
        a = TenantScopedStore(backend, "sellerA")
        b = TenantScopedStore(backend, "sellerB")
        a.save_conversation("c1", _conv("Amara"))
        b.save_conversation("c1", _conv("Kofi"))
        assert a.get_conversation("c1").customer_name == "Amara"
        assert b.get_conversation("c1").customer_name == "Kofi"
        # The shared backend holds both, namespaced.
        assert {cid for cid, _ in backend.list_conversations()} == {"sellerA:c1", "sellerB:c1"}

    def test_list_and_pending_are_scoped(self):
        backend = InMemoryStore({}, {})
        a = TenantScopedStore(backend, "sellerA")
        b = TenantScopedStore(backend, "sellerB")
        a.save_conversation("c1", _conv())
        b.save_conversation("c2", _conv())
        a.set_pending("c1", {"body": "Yes"})
        assert [cid for cid, _ in a.list_conversations()] == ["c1"]
        assert [cid for cid, _ in b.list_conversations()] == ["c2"]
        assert a.has_pending("c1") is True
        assert b.has_pending("c1") is False

    def test_clear_only_affects_one_tenant(self):
        backend = InMemoryStore({}, {})
        a = TenantScopedStore(backend, "sellerA")
        b = TenantScopedStore(backend, "sellerB")
        a.save_conversation("c1", _conv())
        b.save_conversation("c1", _conv())
        a.clear()
        assert a.list_conversations() == []
        assert [cid for cid, _ in b.list_conversations()] == ["c1"]
