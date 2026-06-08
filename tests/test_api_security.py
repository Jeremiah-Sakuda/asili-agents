"""Security-regression tests for the public, unauthenticated API surface.

These pin the remediations from the security deep-dive so they can't regress:
- /api/reset must never destroy durable Atlas data.
- Billable endpoints must be rate-limited and length-capped.
- Security headers must be present on every response.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from asili_agents.api import main as main_module
from asili_agents.api.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


class _RecordingStore:
    """Minimal store double that records whether clear() was called."""

    def __init__(self) -> None:
        self.cleared = False

    def clear(self) -> None:
        self.cleared = True

    # Unused by these tests but part of the protocol surface.
    def list_conversations(self) -> list[tuple[str, Any]]:
        return []


class TestResetNeverWipesDurableData:
    def test_atlas_reset_refuses_to_clear(self, client, monkeypatch):
        store = _RecordingStore()
        monkeypatch.setitem(main_module._state, "store", store)
        monkeypatch.setitem(main_module._state, "data_source", "atlas")

        r = client.post("/api/reset")
        assert r.status_code == 200
        # The durable Atlas store was NOT cleared (no delete_many).
        assert store.cleared is False
        assert r.json()["status"] == "reset-demo-only"

    def test_in_memory_reset_still_clears(self, client, monkeypatch):
        store = _RecordingStore()
        monkeypatch.setitem(main_module._state, "store", store)
        monkeypatch.setitem(main_module._state, "data_source", "demo")

        r = client.post("/api/reset")
        assert r.status_code == 200
        assert store.cleared is True
        assert r.json()["status"] == "reset"


class TestCostControls:
    def test_message_length_is_capped(self, client):
        # An over-long prompt is rejected by validation before any Gemini call.
        r = client.post(
            "/api/run",
            json={"conversation_id": "c1", "message": "x" * 5000},
        )
        assert r.status_code == 422

    def test_baseline_is_rate_limited(self, client, monkeypatch):
        async def fake_baseline(runner, message, **kwargs):
            return ("ok", [])

        monkeypatch.setattr(main_module, "create_baseline_runner", lambda *a, **k: object())
        monkeypatch.setattr(main_module, "run_baseline_async", fake_baseline)

        statuses = set()
        for _ in range(31):
            statuses.add(
                client.post("/api/run/baseline", json={"conversation_id": "c1"}).status_code
            )
        # The 30/min limiter must trip within the burst.
        assert 429 in statuses


class TestSecurityHeaders:
    def test_csp_and_nosniff_present(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "default-src 'none'" in r.headers.get("content-security-policy", "")
        assert r.headers.get("x-content-type-options") == "nosniff"
        assert r.headers.get("x-frame-options") == "DENY"

    def test_oversized_body_rejected(self, client):
        # Declared Content-Length over the cap is rejected up front.
        r = client.post(
            "/api/run",
            content=b"x" * (65 * 1024),
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 413
