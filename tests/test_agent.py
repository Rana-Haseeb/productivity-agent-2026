"""Agent tests — decision routing, approval enforcement, max steps, duplicate detection."""
from __future__ import annotations

from langchain_core.messages import AIMessage

from app.agent.graph import build_agent, get_pending_interrupt, resume_turn, run_turn
from app.agent.nodes import make_tools_node, route_after_agent
from app.config import settings
from app.tools import ToolContext
from tests.conftest import FakeLLM, ai_final, ai_tool


def test_direct_answer_calls_no_tool(fake_repo):
    """A question the model answers directly must not trigger tools."""
    agent = build_agent(fake_repo, FakeLLM([ai_final("High is important; Critical is urgent.")]))
    state = run_turn(agent, "Explain High vs Critical.", thread_id="d1")
    assert state.get("trace", []) == []
    assert state.get("final_outcome") in (None, "completed", None)


def test_single_read_tool_executes(seeded_repo):
    agent = build_agent(
        seeded_repo,
        FakeLLM([ai_tool("list_tasks", {"priority": "Critical"}), ai_final("You have 1.")]),
    )
    state = run_turn(agent, "show critical tasks", thread_id="s1")
    assert [t["tool"] for t in state["trace"]] == ["list_tasks"]


def test_approval_enforced_before_write(fake_repo):
    """A write must PAUSE for approval and NOT execute until approved (100% compliance)."""
    agent = build_agent(
        fake_repo,
        FakeLLM([ai_tool("create_task", {"title": "Buy milk", "priority": "Low"}),
                 ai_final("Created.")]),
    )
    before = len(fake_repo._tasks)
    run_turn(agent, "create a task", thread_id="a1")
    pending = get_pending_interrupt(agent, "a1")
    assert pending is not None                     # paused at the gate
    assert pending["calls"][0]["tool"] == "create_task"
    assert len(fake_repo._tasks) == before         # NOT executed while paused


def test_approval_approve_then_executes(fake_repo):
    agent = build_agent(
        fake_repo,
        FakeLLM([ai_tool("create_task", {"title": "Buy milk", "priority": "Low"}),
                 ai_final("Created.")]),
    )
    before = len(fake_repo._tasks)
    run_turn(agent, "create a task", thread_id="a2")
    resume_turn(agent, {"approved": True}, thread_id="a2")
    assert len(fake_repo._tasks) == before + 1     # executed only after approval


def test_approval_reject_does_not_execute(fake_repo):
    agent = build_agent(
        fake_repo,
        FakeLLM([ai_tool("create_task", {"title": "Buy milk", "priority": "Low"})]),
    )
    before = len(fake_repo._tasks)
    run_turn(agent, "create a task", thread_id="a3")
    state = resume_turn(agent, {"approved": False}, thread_id="a3")
    assert len(fake_repo._tasks) == before         # nothing created
    assert state.get("final_outcome") == "rejected"


def test_max_steps_stops_runaway_loop(fake_repo):
    """If the model keeps calling tools, the run stops at the max-step limit."""
    agent = build_agent(fake_repo, FakeLLM([ai_tool("list_tasks", {"priority": "High"})]))
    state = run_turn(agent, "loop forever", thread_id="m1")
    assert state["final_outcome"] == "max_steps_exceeded"
    assert state["step_count"] == settings.max_steps


def test_duplicate_tool_call_skipped(fake_repo):
    """Two identical calls in one batch: the second is skipped (loop prevention)."""
    ctx = ToolContext(repo=fake_repo, llm=None)
    node = make_tools_node(ctx)
    ai = AIMessage(
        content="",
        tool_calls=[
            {"name": "list_tasks", "args": {}, "id": "a", "type": "tool_call"},
            {"name": "list_tasks", "args": {}, "id": "b", "type": "tool_call"},
        ],
    )
    out = node({"messages": [ai], "executed": {}, "trace": [], "referenced_tasks": []})
    notes = [t.get("note") for t in out["trace"]]
    assert "duplicate-skipped" in notes


def test_route_after_agent_decisions():
    """Unit-test the core decision logic directly."""
    # no tool calls -> END
    assert route_after_agent({"messages": [AIMessage(content="hi")]}) == "__end__"
    # a write tool -> approval
    write = AIMessage(content="", tool_calls=[{"name": "create_task", "args": {}, "id": "x",
                                               "type": "tool_call"}])
    assert route_after_agent({"messages": [write], "step_count": 1}) == "approval"
    # a read tool -> tools
    read = AIMessage(content="", tool_calls=[{"name": "list_tasks", "args": {}, "id": "y",
                                              "type": "tool_call"}])
    assert route_after_agent({"messages": [read], "step_count": 1}) == "tools"
