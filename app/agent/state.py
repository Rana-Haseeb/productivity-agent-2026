"""
Agent state — the typed container that flows through the LangGraph state machine.

A ``TypedDict`` is used (rather than a Pydantic model) because it is the idiomatic LangGraph state
shape: the ``messages`` field uses the ``add_messages`` reducer so message updates append instead of
overwrite. Every value flowing through is still strongly typed (LangChain messages, and Pydantic
tool I/O serialized into tool messages).

State doubles as **session memory** (Requirement 11): ``messages`` is the conversation, and
``referenced_tasks`` remembers the last task list shown so follow-ups like "mark the second one
complete" can be resolved. With a checkpointer, this state persists per conversation ``thread_id``.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    # Conversation (session memory). add_messages => appends, not overwrites.
    messages: Annotated[list[AnyMessage], add_messages]
    # Last task list shown, in order — resolves "the second one" (session memory).
    referenced_tasks: list[dict[str, Any]]
    # Preferences stated during the session (e.g. default working hours).
    preferences: dict[str, Any]
    # A write awaiting approval; set by the approval gate (Phase 5 pause point).
    pending_approval: dict[str, Any] | None
    # Result of the most recent approval gate: "approved" | "rejected" (routes approval -> tools/END).
    approval_decision: str | None
    # Executed (tool, args) signatures -> serialized result, for duplicate/loop detection.
    executed: dict[str, Any]
    # Number of agent (LLM) steps taken this run — enforces the max-step limit.
    step_count: int
    # Per-tool trace for the execution log (name, args, ok, error).
    trace: list[dict[str, Any]]
    # Correlates this run with its execution log row.
    run_id: str
    # How the run ended: completed | awaiting_approval | max_steps_exceeded | error.
    final_outcome: str | None


def initial_state(user_text: str, run_id: str | None = None) -> AgentState:
    """Full state for the FIRST turn of a new conversation thread."""
    return AgentState(
        messages=[HumanMessage(content=user_text)],
        referenced_tasks=[],
        preferences={},
        pending_approval=None,
        executed={},
        step_count=0,
        trace=[],
        run_id=run_id or str(uuid.uuid4()),
        final_outcome=None,
    )


def turn_update(user_text: str, run_id: str | None = None) -> dict[str, Any]:
    """Per-turn reset for an EXISTING thread.

    Resets run-scoped fields (step_count, executed, trace, pending_approval, run_id) while the
    checkpointer preserves conversation-scoped fields (messages, referenced_tasks, preferences).
    """
    return {
        "messages": [HumanMessage(content=user_text)],
        "pending_approval": None,
        "executed": {},
        "step_count": 0,
        "trace": [],
        "run_id": run_id or str(uuid.uuid4()),
        "final_outcome": None,
    }
