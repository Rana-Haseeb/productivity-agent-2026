"""
Agent nodes and decision logic.

Nodes:
- ``agent``      — the LLM decides (may emit tool calls). Increments the step counter.
- ``tools``      — executes tool calls with timeout, retries, duplicate detection, error handling.
- ``approval``   — Phase 4 STUB: records the pending write(s) and STOPS (never executes a write).
                   Phase 5 replaces the stop with a real interrupt()/resume.
- ``max_steps``  — terminal note when the step limit is hit.

Decision logic (``route_after_agent``) is the "when to stop / which way to go" brain:
no tool calls -> done; step limit reached -> stop; a write is requested -> approval; else -> tools.
"""
from __future__ import annotations

import concurrent.futures
import json
import uuid
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.graph import END

from app.agent.prompts import build_system
from app.agent.state import AgentState
from app.config import settings
from app.tools import (
    ToolContext,
    ToolError,
    ToolValidationError,
    openai_tool_schemas,
    requires_approval,
    run_tool,
)

# Routing labels (also node names).
TOOLS = "tools"
APPROVAL = "approval"
MAX_STEPS = "max_steps"

# Bounded pool to enforce a per-tool wall-clock timeout.
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4)
_TRANSIENT = ("connect", "timeout", "temporarily", "network", "reset")


def _signature(name: str, args: dict) -> str:
    return f"{name}:{json.dumps(args, sort_keys=True, default=str)}"


def _needs_approval(tool_call: dict) -> bool:
    try:
        return requires_approval(tool_call["name"])
    except Exception:  # noqa: BLE001 — unknown tool: let tools node report it
        return False


def _friendly_tool_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if any(t in msg for t in ("connect", "network", "getaddrinfo")):
        return "The database is temporarily unavailable. Please try again."
    if "timeout" in msg or "timed out" in msg:
        return "The tool timed out. Please try again."
    return "The tool could not complete this request."


# --------------------------------------------------------------------- agent
def make_agent_node(llm):
    """The LLM step. Closes over the provider-aware LLM service."""
    schemas = openai_tool_schemas()

    def agent_node(state: AgentState) -> dict[str, Any]:
        messages = [SystemMessage(content=build_system())] + list(state.get("messages", []))
        ai = llm.invoke_tools(messages, schemas)
        return {"messages": [ai], "step_count": state.get("step_count", 0) + 1}

    return agent_node


# ----------------------------------------------------------- decision logic
def route_after_agent(state: AgentState):
    """Decide where to go after the agent speaks (the core stop/continue logic)."""
    messages = state.get("messages", [])
    last = messages[-1] if messages else None
    tool_calls = getattr(last, "tool_calls", None) or []

    if not tool_calls:            # produced a final answer → stop
        return END
    if state.get("step_count", 0) >= settings.max_steps:  # step limit → stop
        return MAX_STEPS
    if any(_needs_approval(tc) for tc in tool_calls):      # a write → human approval
        return APPROVAL
    return TOOLS                  # read tools → execute


# ------------------------------------------------------------------ approval
def approval_node(state: AgentState) -> dict[str, Any]:
    """Phase 4 STUB — record the pending write(s) and stop before executing anything."""
    last = state.get("messages", [])[-1]
    pending = [
        {"tool": tc["name"], "args": tc.get("args", {}), "id": tc.get("id")}
        for tc in getattr(last, "tool_calls", [])
        if _needs_approval(tc)
    ]
    names = ", ".join(p["tool"] for p in pending) or "an action"
    note = AIMessage(
        content=(
            f"[Approval required] The following needs your approval before it runs: {names}. "
            "(In Phase 4 the flow pauses here without executing; Phase 5 wires this to a real "
            "interrupt with Approve/Reject.)"
        )
    )
    return {
        "pending_approval": {"calls": pending},
        "messages": [note],
        "final_outcome": "awaiting_approval",
    }


# ----------------------------------------------------------------- max steps
def max_steps_node(state: AgentState) -> dict[str, Any]:
    note = AIMessage(
        content=f"Stopped: reached the maximum of {settings.max_steps} agent steps for one request."
    )
    return {"messages": [note], "final_outcome": "max_steps_exceeded"}


# --------------------------------------------------------------------- tools
def _run_tool_guarded(name: str, args: dict, ctx: ToolContext):
    """Execute one tool with a wall-clock timeout and bounded retries on transient errors."""
    attempts = settings.max_retries_per_tool + 1
    last: Exception | None = None
    for i in range(attempts):
        try:
            future = _EXECUTOR.submit(run_tool, name, args, ctx)
            return future.result(timeout=settings.tool_timeout_seconds)
        except concurrent.futures.TimeoutError as e:
            raise ToolError(
                f"Tool '{name}' timed out after {settings.tool_timeout_seconds}s."
            ) from e
        except ToolValidationError:
            raise  # never retry a validation error
        except Exception as e:  # noqa: BLE001
            last = e
            if any(t in str(e).lower() for t in _TRANSIENT) and i < attempts - 1:
                continue
            raise
    raise last  # pragma: no cover


def make_tools_node(ctx: ToolContext):
    """Execute the last message's tool calls. Closes over the tool context (repo + llm)."""

    def tools_node(state: AgentState) -> dict[str, Any]:
        last = state.get("messages", [])[-1]
        tool_calls = getattr(last, "tool_calls", []) or []
        executed = dict(state.get("executed", {}))
        trace = list(state.get("trace", []))
        referenced = state.get("referenced_tasks", [])
        out: list[ToolMessage] = []

        for tc in tool_calls:
            name = tc["name"]
            args = tc.get("args", {}) or {}
            call_id = tc.get("id") or str(uuid.uuid4())
            sig = _signature(name, args)

            if sig in executed:  # duplicate call → break the loop, reuse prior result
                out.append(ToolMessage(content=executed[sig], tool_call_id=call_id, name=name))
                trace.append({"tool": name, "args": args, "ok": True, "note": "duplicate-skipped"})
                continue

            try:
                result = _run_tool_guarded(name, args, ctx)
                payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
                content = json.dumps(payload, default=str)
                executed[sig] = content
                trace.append({"tool": name, "args": args, "ok": True})
                if name == "list_tasks" and isinstance(payload, dict):
                    referenced = payload.get("tasks", referenced)  # session memory
            except (ToolValidationError, ToolError) as e:
                content = json.dumps({"error": str(e)})
                trace.append({"tool": name, "args": args, "ok": False, "error": str(e)})
            except Exception as e:  # noqa: BLE001 — anything else → safe message, no leak
                content = json.dumps({"error": _friendly_tool_error(e)})
                trace.append({"tool": name, "args": args, "ok": False, "error": str(e)[:200]})

            out.append(ToolMessage(content=content, tool_call_id=call_id, name=name))

        return {
            "messages": out,
            "executed": executed,
            "trace": trace,
            "referenced_tasks": referenced,
        }

    return tools_node
