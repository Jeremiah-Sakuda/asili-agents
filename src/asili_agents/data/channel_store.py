"""Per-seller channel-connection store.

Holds each seller's ChannelConnection (encrypted token + the account id that
receives inbound). Two lookups matter: (seller_id, platform) for the dashboard
and the connect flow, and (platform, external_account_id) to route an inbound
webhook back to the owning seller. One connection per (seller_id, platform).
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from asili_agents.data.models import ChannelConnection

logger = logging.getLogger(__name__)


@runtime_checkable
class ChannelConnectionStore(Protocol):
    def upsert(self, conn: ChannelConnection) -> None: ...
    def get(self, seller_id: str, platform: str) -> ChannelConnection | None: ...
    def list_for_seller(self, seller_id: str) -> list[ChannelConnection]: ...
    def find_by_account(
        self, platform: str, external_account_id: str
    ) -> ChannelConnection | None: ...


class InMemoryChannelStore:
    """Dict-backed store for local dev + tests."""

    def __init__(self) -> None:
        self._by_key: dict[str, ChannelConnection] = {}

    @staticmethod
    def _key(seller_id: str, platform: str) -> str:
        return f"{seller_id}:{platform}"

    def upsert(self, conn: ChannelConnection) -> None:
        self._by_key[self._key(conn.seller_id, conn.platform)] = conn

    def get(self, seller_id: str, platform: str) -> ChannelConnection | None:
        return self._by_key.get(self._key(seller_id, platform))

    def list_for_seller(self, seller_id: str) -> list[ChannelConnection]:
        return [c for c in self._by_key.values() if c.seller_id == seller_id]

    def find_by_account(self, platform: str, external_account_id: str) -> ChannelConnection | None:
        for c in self._by_key.values():
            if c.platform == platform and c.external_account_id == external_account_id:
                return c
        return None


class MongoChannelStore:
    """MongoDB-backed store. ``_id`` = ``{seller_id}:{platform}`` (one per pair)."""

    def __init__(
        self, uri: str, database: str = "asili", *, collection: str = "channel_connections"
    ) -> None:
        from pymongo import MongoClient

        self._client: MongoClient[dict[str, Any]] = MongoClient(
            uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000
        )
        self._client.admin.command("ping")
        self._col = self._client[database][collection]
        # Route inbound webhooks to the owning seller by (platform, account).
        # create_index is idempotent, but several Cloud Run instances can race to
        # build it on a cold start; tolerate that instead of crashing init.
        try:
            self._col.create_index([("platform", 1), ("external_account_id", 1)])
        except Exception:  # noqa: BLE001 — index is a best-effort optimization
            logger.warning("channel_connections index creation skipped", exc_info=True)

    @staticmethod
    def _id(seller_id: str, platform: str) -> str:
        return f"{seller_id}:{platform}"

    def upsert(self, conn: ChannelConnection) -> None:
        data = conn.model_dump(mode="json")
        _id = self._id(conn.seller_id, conn.platform)
        self._col.replace_one({"_id": _id}, {"_id": _id, **data}, upsert=True)

    def get(self, seller_id: str, platform: str) -> ChannelConnection | None:
        doc = self._col.find_one({"_id": self._id(seller_id, platform)})
        if not doc:
            return None
        doc.pop("_id", None)
        return ChannelConnection.model_validate(doc)

    def list_for_seller(self, seller_id: str) -> list[ChannelConnection]:
        out: list[ChannelConnection] = []
        for doc in self._col.find({"seller_id": seller_id}):
            doc.pop("_id", None)
            out.append(ChannelConnection.model_validate(doc))
        return out

    def find_by_account(self, platform: str, external_account_id: str) -> ChannelConnection | None:
        doc = self._col.find_one({"platform": platform, "external_account_id": external_account_id})
        if not doc:
            return None
        doc.pop("_id", None)
        return ChannelConnection.model_validate(doc)
