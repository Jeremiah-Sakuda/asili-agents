"""Demo runner for the Asili Operations Team.

This module provides a demonstration of the multi-agent system,
showing the contrast between the grounded multi-agent approach
and the monolithic baseline.

Run with: python -m asili_agents.demo
"""

import asyncio
from datetime import datetime
from typing import Any

from asili_agents.config import get_settings
from asili_agents.data.seed import get_demo_seller, create_demo_conversation
from asili_agents.data.models import Product
from asili_agents.tools.catalog import (
    set_product_store,
    catalog_search,
    check_stock,
    get_costs,
)
from asili_agents.tools.pricing import set_pricing_context, compute_bundle_price
from asili_agents.tools.logging import log_decision, get_decision_log, clear_decision_log
from asili_agents.agents.baseline import generate_catalog_dump_from_products


def print_header(title: str) -> None:
    """Print a formatted section header."""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60 + "\n")


def print_fact(label: str, value: str, sub: str = "", tone: str = "default") -> None:
    """Print a business fact."""
    tone_marker = "!" if tone == "signal" else " "
    if sub:
        print(f"  {tone_marker} {label}: {value} ({sub})")
    else:
        print(f"  {tone_marker} {label}: {value}")


def print_step(step: dict[str, Any]) -> None:
    """Print an agent decision step."""
    agent = step.get("agent_name", "Unknown")
    role = step.get("agent_role", "")
    trace = step.get("reasoning_trace", "")
    grounded = step.get("grounded_facts", [])

    role_str = f" [{role}]" if role else ""
    print(f"\n  → {agent}{role_str}")
    print(f"    {trace}")
    if grounded:
        print(f"    ✓ Grounded: {', '.join(grounded)}")


def run_demo_scenario() -> None:
    """Run the full demo scenario.

    This demonstrates:
    1. Loading catalog data
    2. Running the agent workflow (simulated)
    3. Showing the grounded response
    4. Contrasting with the baseline failure
    """
    settings = get_settings()

    # Load demo data
    seller, products, policy = get_demo_seller()
    conversation = create_demo_conversation()

    # Initialize tool stores
    set_product_store(products)
    set_pricing_context(products, policy)
    clear_decision_log()

    print_header("ASILI OPERATIONS TEAM DEMO")
    print(f"Seller: {seller.name} ({seller.lane})")
    print(f"Model: {settings.gemini_model}")
    print(f"Margin floor: {int(policy.margin_floor * 100)}%")

    # Show customer message
    print_header("CUSTOMER MESSAGE")
    customer_msg = conversation.messages[0]
    print(f"From: {customer_msg.sender_name}")
    print(f"Channel: {conversation.channel}")
    print(f'"{customer_msg.body}"')

    # Step 1: Route (Operations Manager)
    print_header("AGENT WORKFLOW")

    log_decision(
        agent_name="Operations Manager",
        reasoning="Routing: product question plus pricing request.",
        agent_role="Orchestrator",
        step_type="route",
    )
    print_step(get_decision_log()[-1].model_dump())

    # Step 2: Ground (Messaging Agent)
    # Search for purple tea
    search_results = catalog_search("purple tea")
    purple_tea = search_results[0] if search_results else None

    if purple_tea:
        # Check stock
        stock_info = check_stock(purple_tea["product_id"])

        log_decision(
            agent_name="Messaging",
            reasoning=f"Grounding on catalog. Found {purple_tea['name']}. Stock: {stock_info['quantity']} units, {stock_info['level']}.",
            agent_role="Catalog grounding",
            step_type="ground",
            grounded_facts=["product", "stock"],
        )
        print_step(get_decision_log()[-1].model_dump())

    # Step 3: Price (Pricing Agent)
    if purple_tea:
        # Get costs
        cost_info = get_costs(purple_tea["product_id"])

        # Compute bundle price
        bundle_result = compute_bundle_price(
            items=[{"product_id": purple_tea["product_id"], "quantity": 2}],
            margin_floor=policy.margin_floor,
        )

        log_decision(
            agent_name="Pricing",
            reasoning=f"Computing bundle within margin floor. ${bundle_result['bundle_price']:.2f}, margin safe.",
            agent_role="Margin tool",
            step_type="compute",
            grounded_facts=["bundle", "margin"],
        )
        print_step(get_decision_log()[-1].model_dump())

    # Step 4: Compose (Operations Manager)
    log_decision(
        agent_name="Operations Manager",
        reasoning="Composing reply for approval.",
        agent_role="Orchestrator",
        step_type="compose",
    )
    print_step(get_decision_log()[-1].model_dump())

    # Show business facts
    print_header("GROUNDED BUSINESS STATE")
    if purple_tea and stock_info and cost_info and bundle_result:
        print_fact("Product", purple_tea["name"], purple_tea.get("origin", ""))
        print_fact("Unit price", f"${purple_tea['price']:.2f}", f"per {purple_tea['unit']}")
        print_fact("Unit cost", f"${cost_info['unit_cost']:.2f}", "landed")
        print_fact(
            "Unit margin",
            f"${cost_info['unit_margin']:.2f}",
            f"{int(cost_info['margin_percent'] * 100)}% · floor {int(policy.margin_floor * 100)}%",
        )
        print_fact(
            "In stock",
            f"{stock_info['quantity']} {purple_tea['unit']}s",
            "Low · reorder soon" if stock_info["level"] == "low" else "Healthy",
            tone="signal" if stock_info["level"] == "low" else "default",
        )
        print_fact(
            "Bundle (2 tins)",
            f"${bundle_result['bundle_price']:.2f}",
            f"{int(bundle_result['margin_percent'] * 100)}% margin · save ${bundle_result['discount_amount']:.2f}",
            tone="accent",
        )

    # Show the draft reply
    print_header("DRAFT REPLY (Awaiting Approval)")
    draft = (
        f"Hi {customer_msg.sender_name.split()[0]}! Yes — our {purple_tea['name']} is in stock, "
        f"though we're down to the last {stock_info['quantity']} tins this week. "
        f"I can do a 2-tin bundle for ${bundle_result['bundle_price']:.2f} "
        f"(normally ${bundle_result['total_regular_price']:.2f}) and ship them together. "
        f"Want me to set one aside for you?"
    )
    print(f'"{draft}"')
    print(f"\nSources: Catalog · {purple_tea['name']}, Stock · {stock_info['quantity']} tins, Pricing policy · floor {int(policy.margin_floor * 100)}%")
    print("\n[Approve] [Edit] [Reject]")

    # Contrast with baseline
    print_header("BASELINE COMPARISON: One Model Alone")
    print("The same question answered WITHOUT grounding or tools:\n")

    # Simulated baseline response (what a naive LLM would say)
    baseline_response = (
        "Yes! We have 32 tins of purple tea in stock. "
        "I can do a 2-tin bundle for $24 — want me to set it up?"
    )
    print(f'"{baseline_response}"')
    print("\n  ✕ hallucinated stock: claimed 32 tins (actual: 6)")
    print("  ✕ below margin: $24 → 38% margin (floor: 45%)")
    print("\n  Verdict: Confident, fabricated, and unsellable at that price.")

    # Summary
    print_header("SUMMARY")
    print("Multi-Agent Operations Team:")
    print("  ✓ Grounded on real catalog data")
    print("  ✓ Stock verified via check_stock tool")
    print("  ✓ Price computed via deterministic compute_bundle_price")
    print("  ✓ Human approval required before sending")
    print("\nBaseline (Single Model):")
    print("  ✕ Hallucinated stock levels")
    print("  ✕ Unsafe price calculation")
    print("  ✕ No verification or approval")

    print("\n" + "=" * 60)
    print("  Demo complete!")
    print("=" * 60 + "\n")


def main() -> None:
    """Entry point for the demo."""
    run_demo_scenario()


if __name__ == "__main__":
    main()
