"""
OpenRouter tool-calling probe (documents the model-selection decision, A6/Experiment 6).

Queries OpenRouter's live model list, keeps free models advertising ``tools`` support,
then verifies each returns a VALID ``tool_calls`` response with parseable JSON args.

Run:  python scripts/probe_tool_calling.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
_env = dotenv_values(ROOT / ".env")
KEY = _env.get("OPENROUTER_API_KEY")
BASE_URL = _env.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
assert KEY, "OPENROUTER_API_KEY not found in .env"
HEADERS = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "List the user's tasks, optionally filtered by priority and status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "priority": {
                        "type": "string",
                        "enum": ["Low", "Medium", "High", "Critical"],
                    },
                    "status": {
                        "type": "string",
                        "enum": ["Pending", "In Progress", "Blocked", "Completed", "Cancelled"],
                    },
                },
                "required": ["priority"],
            },
        },
    }
]
MESSAGES = [
    {
        "role": "system",
        "content": "You are a task agent. When a tool applies, you MUST call it rather than "
        "answering in prose.",
    },
    {"role": "user", "content": "Show me all my critical-priority tasks that are still pending."},
]
PREFERRED = [
    "cohere/north-mini-code:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "google/gemma-4-26b-a4b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen-2.5-72b-instruct:free",
]


def get_free_tool_models() -> list[str]:
    r = requests.get(f"{BASE_URL}/models", headers=HEADERS, timeout=30)
    r.raise_for_status()
    out = []
    for m in r.json()["data"]:
        mid = m.get("id", "")
        sp = m.get("supported_parameters") or []
        pricing = m.get("pricing", {}) or {}
        free = mid.endswith(":free") or (
            str(pricing.get("prompt", "1")) in ("0", "0.0")
            and str(pricing.get("completion", "1")) in ("0", "0.0")
        )
        if free and "tools" in sp:
            out.append(mid)
    return sorted(set(out))


def test_model(model: str) -> dict:
    body = {
        "model": model,
        "messages": MESSAGES,
        "tools": TOOLS,
        "tool_choice": "auto",
        "temperature": 0,
        "max_tokens": 900,
    }
    t0 = time.time()
    try:
        r = requests.post(f"{BASE_URL}/chat/completions", headers=HEADERS, json=body, timeout=60)
    except Exception as e:  # noqa: BLE001
        return {"model": model, "ok": False, "reason": f"request error: {e}", "ms": None}
    dt = int((time.time() - t0) * 1000)
    if r.status_code != 200:
        return {"model": model, "ok": False, "reason": f"HTTP {r.status_code}: {r.text[:160]}", "ms": dt}
    j = r.json()
    choices = j.get("choices")
    if not choices:  # known provider bug: choices null
        return {"model": model, "ok": False, "reason": "choices empty/null", "ms": dt}
    msg = choices[0].get("message", {}) or {}
    tcs = msg.get("tool_calls")
    if not tcs:
        return {"model": model, "ok": False, "reason": "no tool_calls (answered in prose)", "ms": dt}
    fn = tcs[0].get("function", {}) or {}
    try:
        args = json.loads(fn.get("arguments", "") or "{}")
        args_ok = isinstance(args, dict)
    except Exception:  # noqa: BLE001
        args, args_ok = fn.get("arguments"), False
    ok = fn.get("name") == "list_tasks" and args_ok
    return {"model": model, "ok": ok, "reason": "OK" if ok else "bad tool/args",
            "tool": fn.get("name"), "args": args, "ms": dt}


def main() -> None:
    free_tool = get_free_tool_models()
    print(f"Found {len(free_tool)} free models advertising 'tools' support.")
    ordered = [m for m in PREFERRED if m in free_tool]
    to_test = (ordered + [m for m in free_tool if m not in ordered])[:6]
    results = []
    for m in to_test:
        res = test_model(m)
        results.append(res)
        print(f"[{'PASS' if res['ok'] else 'FAIL'}] {m} ({res.get('ms')} ms) — {res['reason']}")
        time.sleep(1)
    (Path(__file__).with_name("probe_results.json")).write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    passes = [r for r in results if r["ok"]]
    print(f"\nSUMMARY: {len(passes)}/{len(results)} produced a valid tool_call.")


if __name__ == "__main__":
    main()
