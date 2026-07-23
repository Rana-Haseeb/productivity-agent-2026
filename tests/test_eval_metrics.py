"""Validate the evaluation metric computation with synthetic results (no LLM)."""
from __future__ import annotations

from eval.metrics import aggregate, evaluate_case


def _r(tools, args=None, approval=False, errored=False, ms=100):
    return {"tools_called": tools, "primary_args": args or {}, "approval_requested": approval,
            "errored": errored, "duration_ms": ms}


def test_direct_case_scoring():
    case = {"id": "D1", "category": "direct", "expected_tools": [], "approval_required": False}
    good = evaluate_case(case, _r([]))
    bad = evaluate_case(case, _r(["list_tasks"]))
    assert good["tool_ok"] and not good["invalid"]
    assert not bad["tool_ok"] and bad["invalid"]  # tool on a direct question = invalid


def test_single_tool_and_arg_scoring():
    case = {"id": "S1", "category": "single", "expected_tools": ["list_tasks"],
            "expected_args": {"priority": "Critical"}, "approval_required": False}
    ev = evaluate_case(case, _r(["list_tasks"], {"priority": "Critical"}))
    assert ev["tool_ok"] and ev["arg_ok"]
    wrong_arg = evaluate_case(case, _r(["list_tasks"], {"priority": "High"}))
    assert wrong_arg["tool_ok"] and not wrong_arg["arg_ok"]


def test_approval_compliance_aggregation():
    a = {"id": "A1", "category": "approval", "expected_tools": ["create_task"], "approval_required": True}
    complied = evaluate_case(a, _r(["create_task"], approval=True))
    skipped = evaluate_case(a, _r(["create_task"], approval=False))
    m = aggregate([complied, skipped])
    assert m["approval_compliance_pct"] == 50.0  # 1 of 2 paused


def test_failure_recovery_scoring():
    f = {"id": "F1", "category": "failure", "expected_tools": [], "approval_required": False}
    recovered = evaluate_case(f, _r([], errored=False))
    crashed = evaluate_case(f, _r([], errored=True))
    m = aggregate([recovered, crashed])
    assert m["recovery_rate_pct"] == 50.0


def test_full_pass_aggregate():
    cases = [
        ({"id": "D1", "category": "direct", "expected_tools": [], "approval_required": False}, _r([])),
        ({"id": "S1", "category": "single", "expected_tools": ["list_tasks"],
          "expected_args": {"priority": "Critical"}, "approval_required": False},
         _r(["list_tasks"], {"priority": "Critical"})),
        ({"id": "A1", "category": "approval", "expected_tools": ["create_task"], "approval_required": True},
         _r(["create_task"], approval=True)),
    ]
    m = aggregate([evaluate_case(c, r) for c, r in cases])
    assert m["tool_selection_accuracy_pct"] == 100.0
    assert m["approval_compliance_pct"] == 100.0
    assert m["invalid_action_rate_pct"] == 0.0
