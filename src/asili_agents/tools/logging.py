"""Decision logging tools for observability.

Every agent decision is logged for:
1. Demo visualization (showing multi-agent collaboration)
2. Debugging and troubleshooting
3. Audit trail and compliance
"""

from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel

from asili_agents.data.models import AgentDecision


class DecisionLogEntry(BaseModel):
    """A logged decision entry."""

    id: str
    agent_name: str
    agent_role: str
    step_type: str
    reasoning_trace: str
    grounded_facts: list[str]
    timestamp: datetime


# Per-run decision log, isolated via a ContextVar so concurrent agent runs (each
# request is its own asyncio task with its own context) don't interleave each
# other's steps — which is what lets the API run without a process-wide lock.
_decision_log: ContextVar[list[AgentDecision] | None] = ContextVar("decision_log", default=None)


def _current_log() -> list[AgentDecision]:
    """Return the current context's decision log, creating it on first use."""
    log = _decision_log.get()
    if log is None:
        log = []
        _decision_log.set(log)
    return log


def get_decision_log() -> list[AgentDecision]:
    """Get all logged decisions for the current run, in chronological order."""
    return list(_current_log())


def clear_decision_log() -> None:
    """Start a fresh decision log for the current run/context."""
    _decision_log.set([])


def log_decision(
    agent_name: str,
    reasoning: str,
    grounded_facts: list[str] | None = None,
    agent_role: str = "",
    step_type: str = "",
    inputs: dict[str, Any] | None = None,
    outputs: dict[str, Any] | None = None,
    conversation_id: str | None = None,
    seller_id: str | None = None,
    model_used: str = "",
    tokens_used: int = 0,
    latency_ms: int = 0,
) -> dict[str, Any]:
    """Log an agent decision for observability.

    This tool records what an agent decided and why. Use it after
    making any significant decision to create an audit trail.

    Args:
        agent_name: Name of the agent making the decision
            (e.g., "Operations Manager", "Messaging", "Pricing").
        reasoning: One-line explanation of what was decided and why.
            This will be displayed in the agent activity stream.
        grounded_facts: List of fact IDs that this decision verified
            (e.g., ["product", "stock"]). These facts will be
            highlighted in the business state panel.
        agent_role: Role description (e.g., "Orchestrator", "Catalog grounding").
        step_type: Type of step (e.g., "route", "ground", "compute", "compose").
        inputs: Input data for this decision.
        outputs: Output/result of the decision.
        conversation_id: Associated conversation ID.
        seller_id: Associated seller ID.
        model_used: LLM model used (if any).
        tokens_used: Number of tokens consumed.
        latency_ms: Processing time in milliseconds.

    Returns:
        The logged decision entry with ID and timestamp.

    Example:
        >>> log_decision(
        ...     agent_name="Messaging",
        ...     reasoning="Grounding on catalog. Found Purple Tea. Stock: 6 units, low.",
        ...     grounded_facts=["product", "stock"],
        ...     agent_role="Catalog grounding",
        ...     step_type="ground"
        ... )
        {"id": "...", "agent_name": "Messaging", "reasoning_trace": "...", ...}
    """
    decision = AgentDecision(
        id=uuid4(),
        conversation_id=UUID(conversation_id) if conversation_id else None,
        seller_id=UUID(seller_id) if seller_id else None,
        agent_name=agent_name,
        agent_role=agent_role,
        step_type=step_type,
        reasoning_trace=reasoning,
        grounded_facts=grounded_facts or [],
        inputs=inputs or {},
        outputs=outputs or {},
        model_used=model_used,
        tokens_used=tokens_used,
        latency_ms=latency_ms,
        timestamp=datetime.now(UTC),
    )

    _current_log().append(decision)

    return DecisionLogEntry(
        id=str(decision.id),
        agent_name=decision.agent_name,
        agent_role=decision.agent_role,
        step_type=decision.step_type,
        reasoning_trace=decision.reasoning_trace,
        grounded_facts=decision.grounded_facts,
        timestamp=decision.timestamp,
    ).model_dump()
