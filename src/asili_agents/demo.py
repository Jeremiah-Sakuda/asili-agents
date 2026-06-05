"""Demo runner for the Asili Operations Team.

This module provides a demonstration of the multi-agent system,
showing the contrast between the grounded multi-agent approach
and the monolithic baseline.

Run with: python -m asili_agents.demo
"""

from typing import Any

from asili_agents.config import get_settings
from asili_agents.data.seed import create_demo_conversation, get_demo_seller
from asili_agents.runner import (
    RunResult,
    create_baseline_runner,
    create_runner,
    run_agent,
    run_baseline,
)
from asili_agents.tools.catalog import check_stock, get_costs, set_product_store
from asili_agents.tools.pricing import compute_bundle_price, set_pricing_context


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
    tool_calls = step.get("tool_calls", [])

    role_str = f" [{role}]" if role else ""
    print(f"\n  -> {agent}{role_str}")
    print(f"    {trace}")
    if tool_calls:
        for tc in tool_calls:
            print(f"    Tool: {tc.get('name', 'unknown')}({tc.get('args', {})})")
    if grounded:
        print(f"    Grounded: {', '.join(grounded)}")


def analyze_baseline_failures(response: str, stock_info: dict, bundle_result: dict) -> list[str]:
    """Analyze baseline response for common failure modes."""
    failures = []

    # Check for hallucinated stock
    actual_stock = stock_info.get("quantity", 0)
    # Look for numbers in response that might be stock claims
    import re

    stock_matches = re.findall(r"(\d+)\s*(?:tins?|units?|in stock)", response.lower())
    for match in stock_matches:
        claimed = int(match)
        if claimed != actual_stock:
            failures.append(f"hallucinated stock: claimed {claimed} tins (actual: {actual_stock})")

    # Check for unsafe prices
    price_matches = re.findall(r"\$(\d+\.?\d*)", response)
    margin_floor = 0.45
    for price_str in price_matches:
        price = float(price_str)
        # For a 2-tin bundle, check if price is below margin floor
        total_cost = bundle_result.get("total_cost", 14.80)
        if price > 0 and price < total_cost / (1 - margin_floor):
            margin = (price - total_cost) / price if price > total_cost else 0
            failures.append(
                f"below margin: ${price:.0f} -> {int(margin * 100)}% margin (floor: 45%)"
            )

    return failures


def run_demo_scenario() -> None:
    """Run the full demo scenario with real agent execution.

    This demonstrates:
    1. Loading catalog data
    2. Running the REAL agent workflow (not scripted)
    3. Showing the grounded response
    4. Contrasting with the REAL baseline failure
    """
    settings = get_settings()

    # Load demo data
    seller, products, policy = get_demo_seller()
    conversation = create_demo_conversation()

    # Initialize tool stores (needed for grounded facts display)
    set_product_store(products)
    set_pricing_context(products, policy)

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

    # Create runners
    print_header("INITIALIZING AGENTS")
    print("Creating Operations Manager with sub-agents...")
    ops_runner = create_runner(seller, products, policy)
    print("  - Operations Manager (orchestrator)")
    print("  - Messaging Agent (catalog grounding)")
    print("  - Pricing Agent (margin tool)")

    print("\nCreating Baseline Agent (single model, no tools)...")
    baseline_runner = create_baseline_runner(seller, products)

    # Run the multi-agent system
    print_header("RUNNING MULTI-AGENT SYSTEM")
    print("Executing Operations Manager on customer message...")
    print("(This is a REAL LLM run, not scripted)")
    print()

    result: RunResult = run_agent(ops_runner, customer_msg.body)

    if not result.success:
        print(f"ERROR: Agent execution failed: {result.error}")
        return

    # Show agent steps
    print_header("AGENT WORKFLOW (Real Execution)")
    for step in result.steps:
        print_step(
            {
                "agent_name": step.agent_name,
                "agent_role": step.agent_role,
                "reasoning_trace": step.reasoning_trace,
                "grounded_facts": step.grounded_facts,
                "tool_calls": step.tool_calls,
            }
        )

    # Get grounded business facts for display
    purple_tea = next((p for p in products if "purple" in p.name.lower()), None)
    stock_info = check_stock("Purple Tea") if purple_tea else {}
    cost_info = get_costs("Purple Tea") if purple_tea else {}
    bundle_result = (
        compute_bundle_price(
            items=[{"product_id": str(purple_tea.id), "quantity": 2}],
            margin_floor=policy.margin_floor,
        )
        if purple_tea
        else {}
    )

    # Show business facts
    print_header("GROUNDED BUSINESS STATE")
    if purple_tea and stock_info and cost_info and bundle_result:
        print_fact("Product", purple_tea.name, purple_tea.origin)
        print_fact("Unit price", f"${purple_tea.price:.2f}", f"per {purple_tea.unit}")
        print_fact("Unit cost", f"${cost_info['unit_cost']:.2f}", "landed")
        print_fact(
            "Unit margin",
            f"${cost_info['unit_margin']:.2f}",
            f"{int(cost_info['margin_percent'] * 100)}% - floor {int(policy.margin_floor * 100)}%",
        )
        print_fact(
            "In stock",
            f"{stock_info['quantity']} {purple_tea.unit}s",
            "Low - reorder soon" if stock_info.get("level") == "low" else "Healthy",
            tone="signal" if stock_info.get("level") == "low" else "default",
        )
        if "bundle_price" in bundle_result:
            print_fact(
                "Bundle (2 tins)",
                f"${bundle_result['bundle_price']:.2f}",
                f"{int(bundle_result['margin_percent'] * 100)}% margin - save ${bundle_result['discount_amount']:.2f}",
                tone="accent",
            )

    # Show the agent-composed draft reply
    print_header("DRAFT REPLY (Agent-Composed, Awaiting Approval)")
    if result.draft:
        print(f'"{result.draft}"')
        if result.draft_sources:
            print(f"\nSources: {', '.join(result.draft_sources)}")
    else:
        print("(No draft produced - agent may need more guidance)")

    print("\n[Approve] [Edit] [Reject]")

    # Run the baseline for REAL comparison
    print_header("BASELINE COMPARISON: One Model Alone (Real Run)")
    print("Running baseline agent on the same question...")
    print("(This is a REAL LLM run, not a typed string)")
    print()

    baseline_response, baseline_events = run_baseline(baseline_runner, customer_msg.body)

    if baseline_response:
        print(f'"{baseline_response}"')

        # Analyze failures
        failures = analyze_baseline_failures(baseline_response, stock_info, bundle_result)
        if failures:
            print()
            for failure in failures:
                print(f"  X {failure}")
            print("\n  Verdict: Model response without grounding or tools.")
        else:
            print("\n  (Baseline happened to get this one right - run again for typical failures)")
    else:
        print("(Baseline agent did not produce a response)")

    # Summary
    print_header("SUMMARY")
    print("Multi-Agent Operations Team:")
    print("  - Real LLM execution with ADK Runner")
    print("  - Grounded on real catalog data via tools")
    print("  - Stock verified via check_stock tool")
    print("  - Price computed via deterministic compute_bundle_price")
    print("  - Human approval required before sending")
    print(f"  - Events captured: {len(result.raw_events)}")

    print("\nBaseline (Single Model):")
    print("  - Real LLM execution (no scripted responses)")
    print("  - No tools available")
    print("  - Catalog dump in context only")
    print("  - Prone to hallucination and unsafe pricing")
    print(f"  - Events captured: {len(baseline_events)}")

    print("\n" + "=" * 60)
    print("  Demo complete! All outputs from real model runs.")
    print("=" * 60 + "\n")


def main() -> None:
    """Entry point for the demo."""
    run_demo_scenario()


if __name__ == "__main__":
    main()
