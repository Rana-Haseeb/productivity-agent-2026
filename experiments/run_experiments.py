"""
Experiments (Assignment 6). Each returns a small result dict; ``main`` runs all and saves them.

  python -m experiments.run_experiments                 # all five
  python -m experiments.run_experiments --only 1 3      # selected
  python -m experiments.run_experiments --provider openai --model gpt-4o-mini

Note: experiments make live LLM calls — budget your quota (or use OpenAI). Results save to
experiments/results.json incrementally.

  1. Tool description quality   — detailed vs terse descriptions -> tool-selection accuracy.
  2. Structured vs unstructured — Pydantic structured output vs free-text JSON -> parse failures.
  3. Temperature                — selection accuracy/consistency at 0.0 / 0.5 / 1.0.
  4. Approval prompt design     — is the write-pause robust to prompt wording? (it's structural).
  5. Max agent steps            — completion vs looping vs latency at 2 / 4 / 8 steps.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

import app.config as config
from app.agent.graph import build_agent, get_pending_interrupt, resume_turn, run_turn
from app.agent.prompts import build_system
from app.database.repository import Repository
from app.services.llm_service import LLMService, _extract_json
from app.tools import openai_tool_schemas
from app.tools.planning_tools import ExtractMeetingActionsOutput
from eval.dataset import CASES

OUT = Path(__file__).parent / "results.json"
SINGLE = [c for c in CASES if c["category"] == "single"]
NOTES_SAMPLES = [
    "Sync 7/20: Decided to launch in August. Sara owns the landing page (due 7/28). "
    "Open question: which analytics tool?",
    "Standup: Ali fixed the login bug. We will freeze scope Friday. Unresolved: legal review needed?",
    "Planning: budget approved at 12k. John to draft the brief by Monday. Risk: vendor delay.",
]


def _selected_tool(llm, request: str, schemas: list) -> str | None:
    msgs = [SystemMessage(content=build_system()), HumanMessage(content=request)]
    ai = llm.invoke_tools(msgs, schemas)
    tcs = getattr(ai, "tool_calls", []) or []
    return tcs[0]["name"] if tcs else None


def _short_schemas() -> list:
    schemas = openai_tool_schemas()
    for s in schemas:  # replace detailed descriptions with terse names
        s["function"]["description"] = s["function"]["name"].replace("_", " ")
    return schemas


def exp1_tool_description_quality(llm) -> dict:
    def accuracy(schemas):
        ok = sum(_selected_tool(llm, c["request"], schemas) in c["expected_tools"] for c in SINGLE)
        return round(100 * ok / len(SINGLE), 1)

    return {"detailed_pct": accuracy(openai_tool_schemas()),
            "short_pct": accuracy(_short_schemas()), "n": len(SINGLE)}


def exp2_structured_vs_unstructured(llm) -> dict:
    sys = ("Extract meeting notes into: summary, decisions, action_items, unresolved_questions.")
    s_fail = u_fail = 0
    for note in NOTES_SAMPLES:
        try:
            llm.structured(sys, note, ExtractMeetingActionsOutput)
        except Exception:  # noqa: BLE001
            s_fail += 1
        try:
            raw = llm.complete(sys + " Return JSON only.", note)
            ExtractMeetingActionsOutput.model_validate_json(_extract_json(raw))
        except Exception:  # noqa: BLE001
            u_fail += 1
    n = len(NOTES_SAMPLES)
    return {"n": n, "structured_parse_failures": s_fail, "unstructured_parse_failures": u_fail}


def exp3_temperature(provider, model) -> dict:
    out = {}
    for temp in (0.0, 0.5, 1.0):
        llm = LLMService(provider=provider, model=model, temperature=temp)
        schemas = openai_tool_schemas()
        ok = sum(_selected_tool(llm, c["request"], schemas) in c["expected_tools"] for c in SINGLE)
        out[str(temp)] = round(100 * ok / len(SINGLE), 1)
    return out


def exp4_approval_prompt(repo, llm) -> dict:
    """Approval is enforced by the GRAPH (requires_approval flag), not by the prompt — so the
    write-pause should hold regardless of prompt wording. This measures that robustness."""
    agent = build_agent(repo, llm)
    approval_cases = [c for c in CASES if c["approval_required"]][:4]
    paused = 0
    for c in approval_cases:
        run_turn(agent, c["request"], thread_id=f"exp4_{c['id']}")
        if get_pending_interrupt(agent, f"exp4_{c['id']}"):
            paused += 1
        resume_turn(agent, {"approved": False}, thread_id=f"exp4_{c['id']}")
    return {"n": len(approval_cases), "paused": paused,
            "compliance_pct": round(100 * paused / max(1, len(approval_cases)), 1),
            "note": "Enforced structurally in the graph, not via prompt wording."}


def exp5_max_steps(repo, llm) -> dict:
    request = "Show my pending tasks, then build a work plan for 6 hours, then flag overdue ones."
    original = config.settings.max_steps
    out = {}
    try:
        for n in (2, 4, 8):
            config.settings.max_steps = n
            agent = build_agent(repo, llm)
            t0 = time.time()
            state = run_turn(agent, request, thread_id=f"exp5_{n}")
            out[str(n)] = {
                "steps": state.get("step_count"),
                "outcome": state.get("final_outcome") or "completed",
                "tools": [t["tool"] for t in state.get("trace", [])],
                "latency_ms": int((time.time() - t0) * 1000),
            }
    finally:
        config.settings.max_steps = original
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", type=int, default=[1, 2, 3, 4, 5])
    ap.add_argument("--provider", default=None)
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    repo = Repository()
    llm = LLMService(provider=args.provider, model=args.model)
    print(f"Model: {llm.describe()}  |  experiments: {args.only}\n")

    results = {}
    runners = {
        1: ("tool_description_quality", lambda: exp1_tool_description_quality(llm)),
        2: ("structured_vs_unstructured", lambda: exp2_structured_vs_unstructured(llm)),
        3: ("temperature", lambda: exp3_temperature(args.provider, args.model)),
        4: ("approval_prompt", lambda: exp4_approval_prompt(repo, llm)),
        5: ("max_steps", lambda: exp5_max_steps(repo, llm)),
    }
    for i in args.only:
        name, fn = runners[i]
        print(f"Running experiment {i}: {name} …")
        try:
            results[name] = fn()
            print(f"  -> {results[name]}")
        except Exception as e:  # noqa: BLE001
            results[name] = {"error": str(e)}
            print(f"  ! {e}")
        OUT.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

    print(f"\nSaved: {OUT}")


if __name__ == "__main__":
    main()
