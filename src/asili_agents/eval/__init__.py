"""Trust Scorecard — adversarial evaluation of the multi-agent team vs a baseline.

The scorecard operationalizes the thesis ("the AI ops team that measures its own
honesty") with numbers: it runs hostile customer scenarios through both systems
and scores each reply for hallucinated stock, margin safety, and groundedness
using DETERMINISTIC Python checks against the catalog ground truth — no LLM
judge. The rates are a measurement (they vary run to run); the structural
guarantees (can't invent stock, can't quote below margin) are what hold always.
"""

from asili_agents.eval.scenarios import SCENARIOS, Scenario
from asili_agents.eval.scoring import ReplyScore, aggregate, evaluate_reply

__all__ = ["SCENARIOS", "Scenario", "ReplyScore", "aggregate", "evaluate_reply"]
