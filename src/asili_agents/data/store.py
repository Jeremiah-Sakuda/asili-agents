"""Durable store for conversations + pending drafts.

The approval gate, the inbox, and auditability depend on conversations and their
pending drafts outliving a single request and a single process. This store has
two implementations:

- ``InMemoryStore`` — backed by plain dicts (the API also exposes these as
  ``_state`` for tests). Single-process; fine for local dev and tests.
- ``MongoStore`` — backed by MongoDB collections so state survives restarts and
  is shared across Cloud Run instances (a Telegram draft created on one instance
  can be approved on another). Writes go to app-owned collections, separate from
  the read-only MCP grounding path.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from asili_agents.data.models import Conversation


@runtime_checkable
class ConversationStore(Protocol):
    """Persistence for conversations and their pending drafts."""

    def get_conversation(self, conversation_id: str) -> Conversation | None: ...
    def save_conversation(self, conversation_id: str, conversation: Conversation) -> None: ...
    def list_conversations(self) -> list[tuple[str, Conversation]]: ...
    def get_pending(self, conversation_id: str) -> dict[str, Any] | None: ...
    def set_pending(self, conversation_id: str, draft: dict[str, Any]) -> None: ...
    def delete_pending(self, conversation_id: str) -> None: ...
    def has_pending(self, conversation_id: str) -> bool: ...
    def clear(self) -> None: ...


class InMemoryStore:
    """In-process store backed by the dicts the API keeps in ``_state``."""

    def __init__(
        self,
        conversations: dict[str, Conversation],
        drafts: dict[str, dict[str, Any]],
    ) -> None:
        self._conversations = conversations
        self._drafts = drafts

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        return self._conversations.get(conversation_id)

    def save_conversation(self, conversation_id: str, conversation: Conversation) -> None:
        self._conversations[conversation_id] = conversation

    def list_conversations(self) -> list[tuple[str, Conversation]]:
        return list(self._conversations.items())

    def get_pending(self, conversation_id: str) -> dict[str, Any] | None:
        return self._drafts.get(conversation_id)

    def set_pending(self, conversation_id: str, draft: dict[str, Any]) -> None:
        self._drafts[conversation_id] = draft

    def delete_pending(self, conversation_id: str) -> None:
        self._drafts.pop(conversation_id, None)

    def has_pending(self, conversation_id: str) -> bool:
        return conversation_id in self._drafts

    def clear(self) -> None:
        self._conversations.clear()
        self._drafts.clear()


class MongoStore:
    """MongoDB-backed store. Keys conversations/drafts by ``_id`` = conversation id."""

    def __init__(
        self,
        uri: str,
        database: str = "asili",
        *,
        conversations_collection: str = "conversations",
        drafts_collection: str = "drafts",
    ) -> None:
        from pymongo import MongoClient

        self._client: MongoClient[dict[str, Any]] = MongoClient(uri)
        db = self._client[database]
        self._conversations = db[conversations_collection]
        self._drafts = db[drafts_collection]

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        doc = self._conversations.find_one({"_id": conversation_id})
        if not doc:
            return None
        doc.pop("_id", None)
        return Conversation.model_validate(doc)

    def save_conversation(self, conversation_id: str, conversation: Conversation) -> None:
        data = conversation.model_dump(mode="json")
        self._conversations.replace_one(
            {"_id": conversation_id}, {"_id": conversation_id, **data}, upsert=True
        )

    def list_conversations(self) -> list[tuple[str, Conversation]]:
        out: list[tuple[str, Conversation]] = []
        for doc in self._conversations.find():
            cid = doc.pop("_id")
            out.append((str(cid), Conversation.model_validate(doc)))
        return out

    def get_pending(self, conversation_id: str) -> dict[str, Any] | None:
        doc = self._drafts.find_one({"_id": conversation_id})
        if not doc:
            return None
        doc.pop("_id", None)
        return doc

    def set_pending(self, conversation_id: str, draft: dict[str, Any]) -> None:
        self._drafts.replace_one(
            {"_id": conversation_id}, {"_id": conversation_id, **draft}, upsert=True
        )

    def delete_pending(self, conversation_id: str) -> None:
        self._drafts.delete_one({"_id": conversation_id})

    def has_pending(self, conversation_id: str) -> bool:
        return self._drafts.count_documents({"_id": conversation_id}, limit=1) > 0

    def clear(self) -> None:
        self._conversations.delete_many({})
        self._drafts.delete_many({})
