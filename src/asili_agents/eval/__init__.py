"""Trust Scorecard — adversarial evaluation of the multi-agent team vs a baseline.

The scorecard proves the thesis ("the AI ops team that can prove it never lied")
with numbers: it runs hostile customer scenarios through both systems and scores
each reply for hallucinated stock, margin safety, and groundedness using
DETERMINISTIC Python checks against the catalog ground truth — no LLM judge.
"""

from asili_agents.eval.scenarios import SCENARIOS, Scenario
from asili_agents.eval.scoring import ReplyScore, aggregate, evaluate_reply

__all__ = ["SCENARIOS", "Scenario", "ReplyScore", "aggregate", "evaluate_reply"]
