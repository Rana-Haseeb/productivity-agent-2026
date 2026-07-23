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
from langgraph.types import interrupt

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
_EFFECTS = {
    "create_task": "Create a new task in your task list.",
    "update_task": "Modify fields of an existing task.",
    "complete_task": "Mark a task as Completed (changes stored status).",
    "save_note": "Save a new note to your notes.",
    "draft_follow_up_email": "Produce an email draft (send is simulated).",
}


def _describe_effect(name: str) -> str:
    return _EFFECTS.get(name, "Perform a write action.")


def approval_node(state: AgentState) -> dict[str, Any]:
    """Real human-in-the-loop gate: pause via interrupt(), resume with the caller's decision.

    Runs to ``interrupt()`` and pauses; the graph stays checkpointed until the caller resumes with
    ``{"approved": bool, "reason"?: str}``. Approve → route to tools (executes). Reject → append
    rejection tool-messages and end, executing nothing.
    """
    last = state.get("messages", [])[-1]
    calls = getattr(last, "tool_calls", []) or []
    pending = [
        {
            "tool": tc["name"],
            "args": tc.get("args", {}),
            "id": tc.get("id"),
            "expected_effect": _describe_effect(tc["name"]),
        }
        for tc in calls
        if _needs_approval(tc)
    ]

    # PAUSE. On resume, `decision` is whatever the caller passed to Command(resume=...).
    decision = interrupt({"type": "approval_request", "calls": pending})
    approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)

    if approved:
        return {"approval_decision": "approved", "pending_approval": None}

    reason = decision.get("reason") if isinstance(decision, dict) else None
    payload = {
        "status": "rejected",
        "message": "User rejected this action; nothing was executed."
        + (f" Reason: {reason}" if reason else ""),
    }
    rejection = [
        ToolMessage(
            content=json.dumps(payload),
            tool_call_id=(tc.get("id") or str(uuid.uuid4())),
            name=tc["name"],
        )
        for tc in calls
    ]
    # A clean closing line so the UI shows a human sentence, not raw rejection JSON.
    closing = AIMessage(
        content="Okay — I won't proceed with that action, and nothing was changed."
        + (f" ({reason})" if reason else " Let me know if you'd like something else.")
    )
    return {
        "approval_decision": "rejected",
        "pending_approval": None,
        "messages": rejection + [closing],
        "final_outcome": "rejected",
    }


def route_after_approval(state: AgentState):
    """Approved → execute the tool calls; rejected → return control to the user."""
    return TOOLS if state.get("approval_decision") == "approved" else END


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
                trace.append({"tool": name, "args": args, "ok": True, "result": payload})
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
