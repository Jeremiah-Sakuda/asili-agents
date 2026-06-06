"""Tests for the FastAPI application."""

import pytest
from fastapi.testclient import TestClient

from asili_agents.api.main import app


@pytest.fixture
def client():
    """Create a test client."""
    with TestClient(app) as c:
        yield c


class TestHealthCheck:
    """Tests for the health check endpoint."""

    def test_root_endpoint(self, client):
        """Test the root health check endpoint."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data


class TestSellerEndpoint:
    """Tests for the seller endpoint."""

    def test_get_seller(self, client):
        """Test getting seller information."""
        response = client.get("/api/seller")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Mahaba Tea Co."
        assert data["lane"] == "KE → US"


class TestProductsEndpoint:
    """Tests for the products endpoint."""

    def test_get_products(self, client):
        """Test getting all products."""
        response = client.get("/api/products")
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0

        # Check that Purple Tea is in the catalog
        purple_tea = next(
            (p for p in data if p["name"] == "Purple Tea"),
            None,
        )
        assert purple_tea is not None
        assert purple_tea["price"] == 18.00
        assert purple_tea["stock_level"] == "low"

    def test_product_structure(self, client):
        """Test that products have correct structure."""
        response = client.get("/api/products")
        data = response.json()
        product = data[0]

        assert "id" in product
        assert "sku" in product
        assert "name" in product
        assert "price" in product
        assert "cost" in product
        assert "margin_percent" in product
        assert "stock_quantity" in product
        assert "stock_level" in product


class TestPolicyEndpoint:
    """Tests for the policy endpoint."""

    def test_get_policy(self, client):
        """Test getting business policy."""
        response = client.get("/api/policy")
        assert response.status_code == 200
        data = response.json()
        assert data["margin_floor"] == 0.45
        assert "shipping_note" in data


class TestFactsEndpoint:
    """Tests for the business facts endpoint."""

    def test_get_facts(self, client):
        """Test getting business facts for UI."""
        response = client.get("/api/facts")
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0

        # Check for expected facts
        fact_ids = [f["id"] for f in data]
        assert "product" in fact_ids
        assert "price" in fact_ids
        assert "stock" in fact_ids

    def test_fact_structure(self, client):
        """Test that facts have correct structure."""
        response = client.get("/api/facts")
        data = response.json()
        fact = data[0]

        assert "id" in fact
        assert "key" in fact
        assert "value" in fact
        assert "sub" in fact
        assert "tone" in fact


class TestResetEndpoint:
    """Tests for the reset endpoint."""

    def test_reset_demo(self, client):
        """Test resetting demo state."""
        response = client.post("/api/reset")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "reset"


class TestRunEndpointEventLoop:
    """Regression tests for running agents inside the async endpoints.

    ``run_agent``/``run_baseline`` are synchronous and call ``asyncio.run()``
    internally. The ``/api/run`` endpoints are ``async``, so invoking those
    helpers directly raised ``RuntimeError: asyncio.run() cannot be called from
    a running event loop``. The endpoints must offload them to a worker thread.
    """

    def _fake_result(self, draft):
        import asyncio

        from asili_agents.runner import RunResult

        async def _create_session():
            return True

        # Mirrors the real helper: uses asyncio.run() internally. Without the
        # thread offload in the endpoint this blows up inside the running loop.
        asyncio.run(_create_session())
        return RunResult(
            steps=[],
            draft=draft,
            draft_sources=[],
            facts={},
            raw_events=[],
            success=True,
        )

    def test_run_endpoint_handles_internal_asyncio_run(self, client, monkeypatch):
        """POST /api/run must not 500 due to a nested event loop."""
        from asili_agents.api import main as main_module

        monkeypatch.setattr(main_module, "create_runner", lambda *a, **k: object())
        monkeypatch.setattr(
            main_module,
            "run_agent",
            lambda runner, message: self._fake_result("Yes, purple tea is in stock."),
        )

        response = client.post(
            "/api/run",
            json={"conversation_id": "test-conv", "message": "Do you have purple tea?"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["draft"]["body"] == "Yes, purple tea is in stock."

    def test_baseline_endpoint_handles_internal_asyncio_run(self, client, monkeypatch):
        """POST /api/run/baseline must not 500 due to a nested event loop."""
        import asyncio

        from asili_agents.api import main as main_module

        def fake_run_baseline(runner, message):
            async def _create_session():
                return True

            asyncio.run(_create_session())
            return "Baseline reply", []

        monkeypatch.setattr(main_module, "create_baseline_runner", lambda *a, **k: object())
        monkeypatch.setattr(main_module, "run_baseline", fake_run_baseline)

        response = client.post(
            "/api/run/baseline",
            json={"conversation_id": "test-conv", "message": "Do you have purple tea?"},
        )
        assert response.status_code == 200, response.text
