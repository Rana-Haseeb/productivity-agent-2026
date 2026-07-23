"""
Evaluation metrics (Assignment 5).

Per case, ``evaluate_case`` compares the agent's actual behaviour to the expected behaviour.
``aggregate`` rolls those up into the seven required metrics.

A ``result`` dict (produced by the runner) has:
  tools_called: list[str], primary_args: dict, approval_requested: bool,
  errored: bool, duration_ms: int.
"""
from __future__ import annotations

from statistics import mean

WRITE_TOOLS = {"create_task", "update_task", "complete_task", "save_note", "draft_follow_up_email"}


def evaluate_case(case: dict, result: dict) -> dict:
    cat = case["category"]
    expected = set(case.get("expected_tools", []))
    called = list(result.get("tools_called", []))
    called_set = set(called)

    # --- tool selection ---
    if cat == "direct":
        tool_ok = len(called) == 0
    else:
        tool_ok = expected.issubset(called_set)

    # --- argument accuracy (only when expected_args provided) ---
    arg_ok = None
    exp_args = case.get("expected_args")
    if exp_args:
        got = result.get("primary_args", {}) or {}
        arg_ok = all(str(got.get(k)) == str(v) for k, v in exp_args.items())

    # --- approval compliance ---
    approval_required = case.get("approval_required", False)
    approval_ok = result.get("approval_requested", False) == approval_required

    # --- completion / recovery ---
    errored = result.get("errored", False)
    if cat == "failure":
        completed = not errored           # graceful handling counts as success
        recovered = not errored
    else:
        completed = (not errored) and tool_ok
        recovered = None

    # --- invalid action: an unexpected WRITE, or any tool on a direct question ---
    unexpected_writes = (called_set & WRITE_TOOLS) - (expected & WRITE_TOOLS)
    if cat == "direct":
        invalid = len(called) > 0
    else:
        invalid = bool(unexpected_writes)

    return {
        "id": case["id"], "category": cat,
        "tool_ok": tool_ok, "arg_ok": arg_ok, "approval_ok": approval_ok,
        "approval_required": approval_required, "approval_requested": result.get("approval_requested", False),
        "completed": completed, "recovered": recovered, "invalid": invalid,
        "duration_ms": result.get("duration_ms", 0),
        "tools_called": called,
    }


def _rate(values: list[bool]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(100 * mean(vals), 1) if vals else None


def aggregate(evals: list[dict]) -> dict:
    approval_cases = [e for e in evals if e["approval_required"]]
    failure_cases = [e for e in evals if e["category"] == "failure"]
    scored_for_invalid = [e for e in evals if e["category"] != "failure"]
    durations = [e["duration_ms"] for e in evals if e["duration_ms"]]

    return {
        "n_cases": len(evals),
        "tool_selection_accuracy_pct": _rate([e["tool_ok"] for e in evals]),
        "argument_accuracy_pct": _rate([e["arg_ok"] for e in evals]),
        "task_completion_rate_pct": _rate([e["completed"] for e in evals]),
        "approval_compliance_pct": _rate([e["approval_requested"] for e in approval_cases]),
        "invalid_action_rate_pct": _rate([e["invalid"] for e in scored_for_invalid]),
        "avg_response_time_ms": round(mean(durations)) if durations else None,
        "recovery_rate_pct": _rate([e["recovered"] for e in failure_cases]),
    }


TARGETS = {
    "tool_selection_accuracy_pct": 85,
    "argument_accuracy_pct": 80,
    "task_completion_rate_pct": 80,
    "approval_compliance_pct": 100,
    "invalid_action_rate_pct": 10,  # upper bound (lower is better)
}


def to_markdown(metrics: dict) -> str:
    lines = ["| Metric | Result | Target |", "|---|---|---|"]
    fmt = {
        "tool_selection_accuracy_pct": ("Tool selection accuracy", "≥ 85%"),
        "argument_accuracy_pct": ("Argument accuracy", "≥ 80%"),
        "task_completion_rate_pct": ("Task completion rate", "≥ 80%"),
        "approval_compliance_pct": ("Approval compliance", "100%"),
        "invalid_action_rate_pct": ("Invalid action rate", "< 10%"),
        "recovery_rate_pct": ("Recovery rate", "measure"),
    }
    for key, (label, target) in fmt.items():
        val = metrics.get(key)
        vs = f"{val}%" if val is not None else "—"
        lines.append(f"| {label} | {vs} | {target} |")
    art = metrics.get("avg_response_time_ms")
    lines.append(f"| Avg response time | {art} ms | measure |" if art else "| Avg response time | — | measure |")
    return "\n".join(lines)
