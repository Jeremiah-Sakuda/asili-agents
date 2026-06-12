"""Approval-outcome meter — the autonomy ladder's learning-system evidence.

The trust ladder's claim is that autonomy is *earned*: drafts start fully gated
(L0), and as the seller's edits approach zero they promote intents to
auto-execute (L1+). The proof of that narrative is measured, not asserted:

- **approval rate** — share of drafts the seller sent (approved or edited)
  rather than rejected;
- **unedited rate** — share approved verbatim, the direct trust signal that an
  intent class is ready for promotion;
- **edit distance** — when the seller does edit, how far the draft was from
  what they actually sent (normalized Levenshtein, 0.0 = sent verbatim,
  1.0 = fully rewritten);
- **time-to-send** — seconds from draft creation to the seller's decision, the
  honest measure of the approval-gate latency the product must beat.

Tracked per seller so the "week 1: 64% unedited → week 7: 93%" promotion story
can be told from production data. Pure and dependency-free; meters are
in-process (reset on deploy and via ``/api/reset``), same posture as the
autonomy and cost meters.
"""

from __future__ import annotations

from statistics import median

# Cap edit-distance inputs so a pathological pair can't pin the CPU
# (O(n*m) dynamic programming; 4000*4000 worst case is still fast).
_MAX_EDIT_CHARS = 4000


def normalized_edit_distance(a: str, b: str) -> float:
    """Levenshtein distance normalized to [0, 1] by the longer string.

    0.0 = identical (sent verbatim) · 1.0 = completely rewritten.
    """
    a = (a or "")[:_MAX_EDIT_CHARS]
    b = (b or "")[:_MAX_EDIT_CHARS]
    if a == b:
        return 0.0
    if not a or not b:
        return 1.0
    # Single-row Levenshtein.
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = curr
    return prev[-1] / max(len(a), len(b))


# Per-seller accumulators. Lists stay small at design-partner scale; medians are
# computed on read.
_outcomes: dict[str, dict[str, list[float] | int]] = {}


def _bucket(seller_id: str | None) -> dict[str, list[float] | int]:
    key = seller_id or "_default"
    if key not in _outcomes:
        _outcomes[key] = {
            "approved": 0,
            "edited": 0,
            "rejected": 0,
            "edit_distances": [],
            "times_to_send_s": [],
        }
    return _outcomes[key]


def record_outcome(
    action: str,
    *,
    edit_distance: float | None = None,
    time_to_send_s: float | None = None,
    seller_id: str | None = None,
) -> None:
    """Record one seller decision on a held draft (approve / edit / reject)."""
    b = _bucket(seller_id)
    if action == "approve":
        b["approved"] = int(b["approved"]) + 1  # type: ignore[arg-type]
    elif action == "edit":
        b["edited"] = int(b["edited"]) + 1  # type: ignore[arg-type]
        if edit_distance is not None:
            dists = b["edit_distances"]
            assert isinstance(dists, list)
            dists.append(round(float(edit_distance), 4))
    elif action == "reject":
        b["rejected"] = int(b["rejected"]) + 1  # type: ignore[arg-type]
    if time_to_send_s is not None and time_to_send_s >= 0 and action != "reject":
        times = b["times_to_send_s"]
        assert isinstance(times, list)
        times.append(round(float(time_to_send_s), 2))


def _stats_for(b: dict[str, list[float] | int]) -> dict[str, float | int]:
    approved = int(b["approved"])  # type: ignore[arg-type]
    edited = int(b["edited"])  # type: ignore[arg-type]
    rejected = int(b["rejected"])  # type: ignore[arg-type]
    total = approved + edited + rejected
    dists = b["edit_distances"]
    times = b["times_to_send_s"]
    assert isinstance(dists, list) and isinstance(times, list)
    return {
        "approved": approved,
        "edited": edited,
        "rejected": rejected,
        "total": total,
        "approval_rate": round((approved + edited) / total, 4) if total else 0.0,
        "unedited_rate": round(approved / total, 4) if total else 0.0,
        "avg_edit_distance": round(sum(dists) / len(dists), 4) if dists else 0.0,
        "median_time_to_send_s": round(median(times), 2) if times else 0.0,
    }


def approval_stats() -> dict[str, object]:
    """Aggregate + per-seller approval-ladder metrics."""
    # Merge all buckets for the aggregate view.
    merged: dict[str, list[float] | int] = {
        "approved": 0,
        "edited": 0,
        "rejected": 0,
        "edit_distances": [],
        "times_to_send_s": [],
    }
    for b in _outcomes.values():
        merged["approved"] = int(merged["approved"]) + int(b["approved"])  # type: ignore[arg-type]
        merged["edited"] = int(merged["edited"]) + int(b["edited"])  # type: ignore[arg-type]
        merged["rejected"] = int(merged["rejected"]) + int(b["rejected"])  # type: ignore[arg-type]
        md, bd = merged["edit_distances"], b["edit_distances"]
        mt, bt = merged["times_to_send_s"], b["times_to_send_s"]
        assert isinstance(md, list) and isinstance(bd, list)
        assert isinstance(mt, list) and isinstance(bt, list)
        md.extend(bd)
        mt.extend(bt)
    return {
        **_stats_for(merged),
        "by_seller": {k: _stats_for(v) for k, v in _outcomes.items()},
    }


def reset_approval_stats() -> None:
    """Reset the meter (tests and /api/reset)."""
    _outcomes.clear()
