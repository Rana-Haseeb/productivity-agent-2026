# A8 · Builder Journal

*(Draft grounded in the actual build — personalize the voice before submitting.)*

## What I built
A tool-using AI agent (LangGraph) that manages tasks and notes, extracts meeting action items, and
plans work — with human approval on every write. Ten typed tools, a stateful agent loop with
execution limits, a real `interrupt()` approval gate, 12-field execution logging, semantic note
search (pgvector), a Streamlit UI, and a test/eval/experiment harness (34 passing tests + a 32-case
eval dataset).

## Most difficult technical problem — and the fix
**Making LangGraph's `interrupt()`/checkpointer cooperate with Streamlit's rerun model.** Streamlit
re-executes the whole script on every interaction, while LangGraph pauses a checkpointed run waiting
to be resumed. Naively, the paused run is lost on rerun. **Fix:** hold the *compiled* graph (with its
`MemorySaver` checkpointer) in `st.session_state`, key every conversation by a `thread_id`, detect
the pause with `get_pending_interrupt`, and resume with `Command(resume=decision)`. I verified the
whole approve/reject cycle both headless and live in a browser (DB stayed unchanged while paused).

## Tool-calling errors I observed
- One free model (`nemotron-3-super`) returned `choices: null` — a null response with no message.
  Added an explicit guard that raises a clean error instead of crashing.
- Intermittent `429` upstream rate-limits on free models → added retry with backoff **and** a model
  fallback chain (north-mini → nemotron → gemma) so a dead primary auto-fails over.
- Free models are **slow** (15–40 s per call), which makes a full 30-case eval blow the 50/day cap —
  the graded run should use OpenAI `gpt-4o-mini`.

## Agent behaviour that surprised me (positively)
- It **didn't fabricate**: extracting meeting actions, it gave Sara her stated deadline but left
  Ali's `owner`-only item with `deadline: None` instead of inventing one.
- Session memory worked cleanly: "mark **the first one** complete" resolved to the exact UUID of the
  first task it had listed a turn earlier, and "tomorrow" resolved to the correct date.

## What failed during testing
- A `date` field typed `date | None` **shadowed the `date` type** under `from __future__ import
  annotations` → `TypeError`. Renamed the field (`plan_date`, alias `"date"`).
- The Supabase **direct** connection host is **IPv6-only** and unreachable on my network
  (`getaddrinfo failed`) — switched to the IPv4 **session pooler**.
- Driving Streamlit's chat input headlessly was flaky (a known widget quirk); the app itself works
  with normal typing — verified via trusted keystrokes + DOM inspection.

## What I would redesign
- Make model fallback finer-grained within a single multi-step conversation.
- Move the checkpointer to Postgres for durable cross-session resume (currently in-session).
- Harden edit-before-approve (it replaces the tool-call message by id — works, but subtle).

## What I learned about agent reliability
**Structure beats prompting.** Enforcing approval with a graph flag/`interrupt()` — not a prompt
instruction — makes compliance independent of what the model decides to do. Keeping scheduling
**deterministic** (not model-driven) made it dependable and explainable. **Typed schemas** caught
malformed/hallucinated arguments before they touched the database. And **observability** (the 12-field
log) turned "did it work?" into something I can actually inspect.

## Goals for Week 4
Multi-user support with Row-Level Security and per-user tool permissions; real calendar/email
integrations behind the same approval gate; a Postgres-backed checkpointer; an explicit
prompt-injection regression suite; and production observability (tracing, cost/latency dashboards).
