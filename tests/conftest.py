"""Pytest configuration and fixtures."""


import pytest

from asili_agents.data.models import Conversation, Policy, Product, Seller
from asili_agents.data.seed import create_demo_conversation, get_demo_seller
from asili_agents.tools.catalog import set_product_store
from asili_agents.tools.logging import clear_decision_log
from asili_agents.tools.pricing import set_pricing_context


@pytest.fixture
def demo_data():
    """Load demo data for tests."""
    seller, products, policy = get_demo_seller()
    return {
        "seller": seller,
        "products": products,
        "policy": policy,
    }


@pytest.fixture
def demo_seller(demo_data) -> Seller:
    """Get the demo seller."""
    return demo_data["seller"]


@pytest.fixture
def demo_products(demo_data) -> list[Product]:
    """Get the demo products."""
    return demo_data["products"]


@pytest.fixture
def demo_policy(demo_data) -> Policy:
    """Get the demo policy."""
    return demo_data["policy"]


@pytest.fixture
def demo_conversation() -> Conversation:
    """Get a demo conversation."""
    return create_demo_conversation()


@pytest.fixture
def purple_tea(demo_products) -> Product:
    """Get the Purple Tea product."""
    return next(p for p in demo_products if "purple" in p.name.lower())


@pytest.fixture(autouse=True)
def setup_tools(demo_products, demo_policy):
    """Set up tool stores before each test."""
    set_product_store(demo_products)
    set_pricing_context(demo_products, demo_policy)
    clear_decision_log()
    yield
    clear_decision_log()
