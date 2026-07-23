"""
Streamlit UI for the Personal Productivity & Task Execution Agent.

Layout: sidebar (brand, theme, model switch, live metrics) + two columns — a conversation panel
(chat history, six live status states, and the human-approval panel) beside tabbed live data
(Tasks / Notes / Execution Logs).

The compiled agent (with its checkpointer) is held in ``st.session_state`` so the approval
interrupt/resume survives Streamlit reruns.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime

# Make the `app` package importable when run via `streamlit run app/main.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

# On Streamlit Community Cloud, secrets arrive via st.secrets (not env vars). Bridge them into the
# environment BEFORE app.config is imported, so the same os.getenv-based config works everywhere.
try:
    for _k, _v in st.secrets.items():
        os.environ.setdefault(_k, str(_v))
except Exception:  # noqa: BLE001 — no secrets file locally; .env is used instead
    pass

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from app import theme
from app.agent.graph import build_agent, get_pending_interrupt
from app.agent.state import initial_state, turn_update
from app.config import PROVIDERS, settings
from app.database.models import Priority, Status, TaskFilter
from app.database.repository import Repository, RepositoryError
from app.observability.run_logger import RunLogger
from app.services.llm_service import LLMError, LLMService

ss = st.session_state

st.set_page_config(page_title="Productivity Agent", page_icon=theme.page_icon(), layout="wide")


# --------------------------------------------------------------------- setup
def setup() -> str | None:
    """Initialise shared resources once per session. Returns an error string or None."""
    if ss.get("initialized"):
        return None
    try:
        ss.repo = Repository()
        ss.repo.ping()
        ss.provider = settings.provider
        ss.model = settings.active_model()
        ss.llm = LLMService()
        ss.agent = build_agent(ss.repo, ss.llm)
        ss.logger = RunLogger(ss.repo)
        ss.thread_id = str(uuid.uuid4())
        ss.pending = None
        ss.initialized = True
        return None
    except Exception as e:  # noqa: BLE001
        return _friendly(e)


def _friendly(exc: Exception) -> str:
    if isinstance(exc, (LLMError, RepositoryError)):
        return str(exc)
    msg = str(exc)
    if "DATABASE_URL" in msg or "connect" in msg.lower():
        return "Could not reach the database. Check DATABASE_URL (Supabase session pooler)."
    return "Something went wrong. Please try again."


def cfg() -> dict:
    return {
        "configurable": {"thread_id": ss.thread_id},
        "recursion_limit": settings.max_steps * 2 + 2,
    }


def current_state() -> dict:
    try:
        return ss.agent.get_state(cfg()).values or {}
    except Exception:  # noqa: BLE001
        return {}


# ------------------------------------------------------------- run one turn
def process_turn(payload, is_resume: bool) -> None:
    """Stream a turn (new request or approval resume), showing the six status states live."""
    status = st.status("🧠 Thinking…", expanded=True)
    try:
        if is_resume:
            stream_input = Command(resume=payload)
        else:
            exists = bool(current_state())
            stream_input = turn_update(payload) if exists else initial_state(payload)

        for chunk in ss.agent.stream(stream_input, cfg(), stream_mode="updates"):
            _reflect_status(status, chunk)

        pending = get_pending_interrupt(ss.agent, ss.thread_id)
        if pending:
            ss.pending = pending
            status.update(label="✋ Waiting for your approval", state="complete")
        else:
            ss.pending = None
            try:  # logging must never break the UX
                ss.logger.record(current_state(), ss.run_input, ss.llm.last_used_model, ss.run_start)
            except Exception:  # noqa: BLE001
                pass
            status.update(label="✅ Final response ready", state="complete")
    except Exception as e:  # noqa: BLE001
        ss.pending = None
        status.update(label="⚠️ Error", state="error")
        st.error(_friendly(e))


def _reflect_status(status, chunk: dict) -> None:
    """Map a streamed node update to one of the six operational status states."""
    for node, update in chunk.items():
        if node == "agent":
            msgs = (update or {}).get("messages") or []
            last = msgs[-1] if msgs else None
            if getattr(last, "tool_calls", None):
                names = ", ".join(tc["name"] for tc in last.tool_calls)
                status.update(label=f"🔧 Selecting tool: {names}")
                st.write(f"Selecting tool(s): **{names}**")
            else:
                status.update(label="✍️ Composing response…")
        elif node == "tools":
            trace = (update or {}).get("trace") or []
            tool = trace[-1]["tool"] if trace else "tool"
            status.update(label=f"⚙️ Executing: {tool}")
            st.write(f"Executed **{tool}**")
        elif node in ("approval", "__interrupt__"):
            status.update(label="✋ Waiting for your approval")
        elif node == "max_steps":
            status.update(label="🛑 Reached step limit")


# ------------------------------------------------------------- conversation
def render_history() -> None:
    msgs = current_state().get("messages", [])
    if not msgs:
        st.markdown(
            '<div class="empty"><div class="big">💬</div>'
            "Ask me to plan your day, turn meeting notes into tasks, or find overdue work."
            "</div>",
            unsafe_allow_html=True,
        )
        return
    for m in msgs:
        if isinstance(m, HumanMessage):
            with st.chat_message("user"):
                st.write(m.content)
        elif isinstance(m, AIMessage):
            if m.content:
                with st.chat_message("assistant"):
                    st.write(m.content)
            for tc in getattr(m, "tool_calls", []) or []:
                st.caption(f"🔧 proposed `{tc['name']}`  ·  args: {json.dumps(tc.get('args', {}))}")
        elif isinstance(m, ToolMessage):
            st.caption(f"⚙️ result from `{m.name}`")


def render_approval_panel() -> None:
    if not ss.get("pending"):
        return
    calls = ss.pending.get("calls", [])
    st.markdown("---")
    st.markdown(
        '<div class="tool-card"><h4>✋ Approval required</h4>'
        "This is a write action. Review the details, edit the arguments if needed, "
        "then Approve or Reject.</div>",
        unsafe_allow_html=True,
    )
    for i, c in enumerate(calls):
        st.markdown(f"**Tool:** `{c['tool']}`  \n**Expected effect:** {c.get('expected_effect', '')}")
        st.text_area(
            "Arguments (editable JSON)",
            value=json.dumps(c.get("args", {}), indent=2, default=str),
            key=f"appr_args_{i}",
            height=120,
        )
    approve_col, reject_col = st.columns(2)
    if approve_col.button("✅ Approve", use_container_width=True, type="primary"):
        edited = {}
        for i, c in enumerate(calls):
            try:
                new_args = json.loads(ss[f"appr_args_{i}"])
            except Exception:  # noqa: BLE001
                new_args = c.get("args", {})
            if new_args != c.get("args", {}) and c.get("id"):
                edited[c["id"]] = new_args
        decision = {"approved": True}
        if edited:
            decision["edited_args"] = edited
        ss._resume = decision
        st.rerun()
    if reject_col.button("❌ Reject", use_container_width=True):
        ss._resume = {"approved": False}
        st.rerun()


# --------------------------------------------------------------- data tabs
def render_tasks_tab() -> None:
    c1, c2 = st.columns(2)
    status_opts = ["(any)"] + [s.value for s in Status]
    prio_opts = ["(any)"] + [p.value for p in Priority]
    fstatus = c1.selectbox("Status", status_opts, key="f_status")
    fprio = c2.selectbox("Priority", prio_opts, key="f_prio")
    flt = TaskFilter(
        status=Status(fstatus) if fstatus != "(any)" else None,
        priority=Priority(fprio) if fprio != "(any)" else None,
        limit=200,
    )
    tasks = ss.repo.list_tasks(flt)
    st.caption(f"{len(tasks)} task(s)")
    for t in tasks:
        due = t.due_date.isoformat() if t.due_date else "—"
        tags = " ".join(f'<span class="match-badge">{tag}</span>' for tag in t.tags)
        st.markdown(
            f'<div class="doc-row"><div class="doc-name">{t.title} '
            f'<span class="match-badge">{t.priority.value}</span></div>'
            f'<div class="doc-meta">{t.status.value} · due {due} {tags}</div></div>',
            unsafe_allow_html=True,
        )


def render_notes_tab() -> None:
    q = st.text_input("Search notes (semantic)", key="note_q", placeholder="e.g. marketing budget")
    if q:
        hits = ss.repo.search_notes_semantic(q, k=5)
        st.caption(f"{len(hits)} match(es)")
        for h in hits:
            st.markdown(
                f'<div class="cite-card"><div class="ct">{h.note.title}'
                f'<span class="cite-badge">{h.score:.2f}</span></div>'
                f'<div class="cite-snip">{h.note.content[:180]}…</div></div>',
                unsafe_allow_html=True,
            )
    else:
        # No query → list recent notes (empty keyword matches all via ILIKE '%%').
        recent = ss.repo.search_notes_keyword("", k=50)
        st.caption(f"{len(recent)} note(s)")
        for h in recent:
            st.markdown(
                f'<div class="doc-row"><div class="doc-name">{h.note.title} '
                f'<span class="match-badge">{h.note.category}</span></div>'
                f'<div class="doc-meta">{h.note.content[:140]}…</div></div>',
                unsafe_allow_html=True,
            )


def render_logs_tab() -> None:
    logs = ss.logger.recent(limit=25)
    st.caption(f"{len(logs)} run(s) logged")
    for lg in logs:
        head = f"{lg.final_outcome or '—'} · {', '.join(lg.tools_called) or 'no tools'}"
        with st.expander(f"🧾 {lg.start_time:%Y-%m-%d %H:%M} · {head}"):
            st.markdown(f"**Request:** {lg.user_request}")
            st.markdown(
                f"**Model:** `{lg.model}` · **Approval:** {lg.approval_status} · "
                f"**Duration:** {lg.duration_ms} ms"
            )
            if lg.tools_called:
                st.markdown(f"**Tools:** {', '.join(lg.tools_called)}")
            if lg.errors:
                st.markdown(f"**Errors:** {lg.errors}")
            st.markdown(f"**Run id:** `{lg.run_id}`")


# ----------------------------------------------------------------- sidebar
def render_sidebar() -> None:
    with st.sidebar:
        theme.sidebar_brand("Productivity Agent", "Tool-using AI agent · Week 3")
        theme.appearance_toggle()

        st.markdown('<div class="side-title">Model</div>', unsafe_allow_html=True)
        providers = list(PROVIDERS)
        prov = st.selectbox("Provider", providers, index=providers.index(ss.provider))
        models = PROVIDERS[prov].models
        midx = models.index(ss.model) if ss.model in models else 0
        model = st.selectbox("Model", models, index=midx)
        if prov != ss.provider or model != ss.model:
            ss.provider, ss.model = prov, model
            ss.llm = LLMService(provider=prov, model=model)
            ss.agent = build_agent(ss.repo, ss.llm)
            ss.thread_id = str(uuid.uuid4())
            ss.pending = None
            st.rerun()

        st.markdown('<div class="side-title">Session</div>', unsafe_allow_html=True)
        if st.button("🆕 New conversation", use_container_width=True):
            ss.thread_id = str(uuid.uuid4())
            ss.pending = None
            st.rerun()

        # Live metrics
        all_tasks = ss.repo.list_tasks(TaskFilter(limit=500))
        pending_n = sum(1 for t in all_tasks if t.status == Status.PENDING)
        done_n = sum(1 for t in all_tasks if t.status == Status.COMPLETED)
        from datetime import date

        overdue_n = sum(
            1 for t in all_tasks
            if t.due_date and t.due_date < date.today()
            and t.status not in (Status.COMPLETED, Status.CANCELLED)
        )
        st.markdown('<div class="side-title">Overview</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="metric-row">'
            f'<div class="metric"><div class="v">{len(all_tasks)}</div><div class="l">Tasks</div></div>'
            f'<div class="metric"><div class="v">{pending_n}</div><div class="l">Pending</div></div>'
            f'</div><div class="metric-row">'
            f'<div class="metric"><div class="v">{done_n}</div><div class="l">Done</div></div>'
            f'<div class="metric"><div class="v">{overdue_n}</div><div class="l">Overdue</div></div>'
            f"</div>",
            unsafe_allow_html=True,
        )
        st.caption(f"Limits: {settings.max_steps} steps · {settings.max_retries_per_tool} retries · "
                   f"{settings.tool_timeout_seconds}s timeout")


# -------------------------------------------------------------------- main
def main() -> None:
    theme.inject_css(ss.get("dark_mode", True))
    err = setup()
    if err:
        theme.render_hero("Productivity Agent", "Tool-using AI agent")
        st.error(err)
        st.stop()

    render_sidebar()
    theme.render_hero(
        "Personal Productivity Agent",
        "Plan work, extract action items, manage tasks & notes — with human approval on every write.",
        pill="LangGraph · Supabase · approval-gated",
    )

    left, right = st.columns([1.15, 1], gap="large")

    with left:
        st.markdown('<div class="side-title">Conversation</div>', unsafe_allow_html=True)
        render_history()

        # Process a queued new turn or an approval resume (status renders here, in-column).
        if ss.get("_pending_input"):
            ss.run_input = ss._pending_input
            ss.run_start = datetime.now()
            ss._pending_input = None
            process_turn(ss.run_input, is_resume=False)
            st.rerun()
        if ss.get("_resume") is not None:
            decision = ss._resume
            ss._resume = None
            process_turn(decision, is_resume=True)
            st.rerun()

        render_approval_panel()

    with right:
        st.markdown('<div class="side-title">Workspace</div>', unsafe_allow_html=True)
        tab_tasks, tab_notes, tab_logs = st.tabs(["✅ Tasks", "🗒️ Notes", "📜 Logs"])
        with tab_tasks:
            render_tasks_tab()
        with tab_notes:
            render_notes_tab()
        with tab_logs:
            render_logs_tab()

    # Chat input (pinned bottom). Blocked while an approval is pending.
    prompt = st.chat_input("Ask the agent to plan, create tasks, extract actions, find overdue work…")
    if prompt:
        if ss.get("pending"):
            st.warning("Please approve or reject the pending action first.")
        else:
            ss._pending_input = prompt
            st.rerun()


main()
