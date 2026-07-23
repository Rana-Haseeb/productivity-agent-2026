"""
Evaluation runner (Assignment 5).

  python -m eval.run_eval                      # all 32 cases, default provider
  python -m eval.run_eval --limit 6            # first 6 cases (quick smoke)
  python -m eval.run_eval --provider openai --model gpt-4o-mini   # graded run

Approval cases are auto-REJECTED after the pause so the run never mutates the database — we still
measure that the agent correctly paused (approval compliance) and selected the right tool. Results
are saved incrementally to eval/results.json (survives an interrupted run / rate-limit stop).
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from app.agent.graph import build_agent, get_pending_interrupt, resume_turn, run_turn
from app.database.repository import Repository
from app.services.llm_service import LLMService
from eval.dataset import CASES, counts
from eval.metrics import aggregate, evaluate_case, to_markdown

OUT_DIR = Path(__file__).parent
RESULTS = OUT_DIR / "results.json"
METRICS = OUT_DIR / "metrics.json"
SUMMARY = OUT_DIR / "A5_results.md"


def _run_case(agent, case: dict) -> dict:
    thread = f"eval_{case['id']}"
    t0 = time.time()
    errored = False
    try:
        state = run_turn(agent, case["request"], thread_id=thread)
        pending = get_pending_interrupt(agent, thread)
        approval_requested = pending is not None
        proposed = pending["calls"] if pending else []
        if pending:  # reject to avoid DB writes; we've already recorded the pause
            state = resume_turn(agent, {"approved": False}, thread_id=thread)
    except Exception as e:  # noqa: BLE001
        if any(s in str(e).lower() for s in ("429", "rate", "quota")):
            raise  # bubble up so the caller can stop and save partial
        errored = True
        state, approval_requested, proposed = {"trace": []}, False, []

    duration_ms = int((time.time() - t0) * 1000)
    pairs = [(t["tool"], t.get("args", {})) for t in state.get("trace", [])]
    pairs += [(c["tool"], c.get("args", {})) for c in proposed]
    tools_called = [name for name, _ in pairs]

    expected = set(case.get("expected_tools", []))
    primary_args = next((a for n, a in pairs if n in expected), (pairs[0][1] if pairs else {}))

    return {
        "tools_called": tools_called,
        "primary_args": primary_args,
        "approval_requested": approval_requested,
        "errored": errored,
        "duration_ms": duration_ms,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=len(CASES))
    ap.add_argument("--provider", default=None)
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    repo = Repository()
    llm = LLMService(provider=args.provider, model=args.model)
    agent = build_agent(repo, llm)

    print(f"Dataset: {counts()}  (total {len(CASES)})")
    print(f"Model: {llm.describe()}  |  running {min(args.limit, len(CASES))} case(s)\n")

    evals, raw = [], []
    for case in CASES[: args.limit]:
        try:
            result = _run_case(agent, case)
        except Exception as e:  # noqa: BLE001 — rate limit: stop, keep partial
            print(f"\n! Stopped at {case['id']} (rate limit?): {e}")
            break
        ev = evaluate_case(case, result)
        evals.append(ev)
        raw.append({"case": case["id"], **result, "eval": ev})
        flag = "ok " if ev["tool_ok"] else "MISS"
        print(f"[{flag}] {case['id']} ({case['category']}) tools={result['tools_called']} "
              f"approval={result['approval_requested']} {result['duration_ms']}ms")
        RESULTS.write_text(json.dumps(raw, indent=2, default=str), encoding="utf-8")  # incremental

    metrics = aggregate(evals)
    metrics["generated_at"] = datetime.now().isoformat()
    metrics["model"] = llm.describe()
    METRICS.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    SUMMARY.write_text(
        f"# A5 — Evaluation Results\n\nModel: `{llm.describe()}` · cases: {len(evals)} · "
        f"{metrics['generated_at']}\n\n{to_markdown(metrics)}\n", encoding="utf-8"
    )
    print("\n=== METRICS ===")
    for k, v in metrics.items():
        print(f"  {k}: {v}")
    print(f"\nSaved: {RESULTS.name}, {METRICS.name}, {SUMMARY.name}")


if __name__ == "__main__":
    main()
