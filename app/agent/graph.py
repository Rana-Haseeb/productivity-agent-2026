"""
The agent graph — a LangGraph ``StateGraph`` binding the tools into a stateful loop.

Topology::

        START
          |
          v
       [agent] --no tool calls----------> END
          |  \\--step limit reached-----> [max_steps] --> END
          |  \\--write requested--------> [approval]  --> END   (Phase 4 stub: pause, don't execute)
          |
          v (read tools)
       [tools] --> back to [agent]

Limits (Requirement 9, documented): max 8 agent steps (enforced in decision logic AND as a
``recursion_limit`` backstop), 2 retries/tool, 30s tool timeout, duplicate-call detection.
The compiled graph is stateful via a checkpointer keyed by ``thread_id`` (Phase 5 keeps it in
Streamlit ``session_state`` so approval pause/resume cooperates with reruns).
"""
from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.agent.nodes import (
    APPROVAL,
    MAX_STEPS,
    TOOLS,
    approval_node,
    make_agent_node,
    make_tools_node,
    max_steps_node,
    route_after_agent,
    route_after_approval,
)
from app.agent.state import AgentState, initial_state, turn_update
from app.config import settings
from app.tools import ToolContext


def build_agent(repo, llm, checkpointer=None):
    """Compile the agent graph. ``repo`` and ``llm`` are injected (never global)."""
    ctx = ToolContext(repo=repo, llm=llm)

    graph = StateGraph(AgentState)
    graph.add_node("agent", make_agent_node(llm))
    graph.add_node(TOOLS, make_tools_node(ctx))
    graph.add_node(APPROVAL, approval_node)
    graph.add_node(MAX_STEPS, max_steps_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        route_after_agent,
        {TOOLS: TOOLS, APPROVAL: APPROVAL, MAX_STEPS: MAX_STEPS, END: END},
    )
    graph.add_edge(TOOLS, "agent")
    graph.add_conditional_edges(APPROVAL, route_after_approval, {TOOLS: TOOLS, END: END})
    graph.add_edge(MAX_STEPS, END)

    return graph.compile(checkpointer=checkpointer or MemorySaver())


def run_turn(graph, user_text: str, thread_id: str = "default", run_id: str | None = None) -> AgentState:
    """Run one user turn on a conversation thread and return the final state.

    ``recursion_limit`` is a hard backstop; the explicit max-step logic normally stops first.
    """
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": settings.max_steps * 2 + 2,
    }
    thread_exists = bool(graph.get_state(config).values)
    update = turn_update(user_text, run_id) if thread_exists else initial_state(user_text, run_id)
    return graph.invoke(update, config=config)


def resume_turn(graph, decision, thread_id: str = "default"):
    """Resume a paused run with the approval decision, e.g. ``{"approved": True}``."""
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": settings.max_steps * 2 + 2,
    }
    return graph.invoke(Command(resume=decision), config=config)


def get_pending_interrupt(graph, thread_id: str = "default"):
    """Return the approval-request payload if the run is paused at the gate, else None."""
    snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
    if getattr(snapshot, "next", None):
        for task in getattr(snapshot, "tasks", []):
            interrupts = getattr(task, "interrupts", None)
            if interrupts:
                return interrupts[0].value
    return None
