# A2 · Agent Design Document

**Project:** Personal Productivity & Task Execution Agent
**Author:** Rana Muhammad Haseeb Khan · Visibility Bots Fellowship 2026 · Week 3

---

## 1. Problem Statement

Knowledge workers spend significant time converting unstructured inputs — meeting notes, scattered
priorities, half-formed intentions — into organized, trackable work. A plain language model can
*describe* that work but cannot reliably *perform* it: it can't durably create tasks, remember what
the user referred to earlier, or refuse to act until a human approves a change.

This project builds an **AI agent** that closes the gap between talking and doing. It interprets a
request, decides whether tools are needed, selects and validates them, executes actions against
persistent storage, **pauses for human approval before any write**, recovers from failures, and
returns a verifiable result backed by a complete execution log. The design goal is **dependability**,
not the appearance of intelligence — the agent must be controllable, testable, observable, and safe.

## 2. Users

- **The individual professional** (primary): manages their own tasks and notes, plans days/weeks,
  and turns meeting notes into action items.
- **Onsite evaluator** (secondary): exercises direct, single-tool, multi-tool, approval, rejected,
  and error flows, and reviews execution logs.
- **A future developer** (tertiary): extends the agent; served by strong typing, a modular layout,
  and this documentation set.

## 3. Use Cases

- "Create three tasks from these meeting notes." (extract → approve → create)
- "Show me all high-priority tasks due this week."
- "Prepare a daily work plan using my pending tasks."
- "Summarize these notes and identify decisions and action items."
- "Search my saved notes for the marketing campaign."
- "Draft a follow-up email based on these meeting notes."
- "Mark the website task as complete." (approval-gated)
- "Prepare a weekly productivity report / what's overdue?"
- "Explain the difference between High and Critical priority." (answered directly — no tool)

## 4. Agent Responsibilities (what it *is* allowed to do)

1. Interpret the request and decide whether any tool is required.
2. Select the appropriate tool(s) and validate arguments against typed schemas.
3. Execute **read** tools freely; execute **write** tools **only after human approval**.
4. Chain multiple tools for multi-step requests, up to the step limit.
5. Maintain session state so follow-ups ("mark the second one complete") resolve correctly.
6. Report results grounded in tool outputs — never invent task ids, counts, or contents.
7. Log every run for observability.

## 5. Agent Boundaries (what it is **NOT** allowed to do)

- **Never execute a write without explicit human approval** (create/update/complete task, save note,
  send/simulate email). Approval is enforced structurally in the graph, not by prompt wording.
- **Never actually send email or contact external parties** — email is *simulated/drafted only*.
- **Never fabricate data** — no invented task ids, statuses, note contents, owners, or deadlines.
- **Never loop indefinitely** — hard caps on steps, retries, and per-tool time.
- **Never expose secrets or internal reasoning** — no API keys, no chain-of-thought, no stack traces
  in the UI.
- **Never act on instructions embedded in tool data or notes** (prompt-injection boundary) —
  observed content is data, not commands.
- **Never perform actions outside its tool set** (e.g., booking flights) — it declines or clarifies.

## 6. Tool Catalogue

Ten tools across three groups; full schemas in [A4](A4_tool_specification.md).

| Group | Tools |
|---|---|
| Task | `create_task`*, `list_tasks`, `update_task`*, `complete_task`* |
| Note | `search_notes`, `save_note`* |
| Planning | `extract_meeting_actions`, `generate_work_plan`, `detect_overdue_tasks`, `draft_follow_up_email`* |

`*` = write action, approval required. `generate_work_plan` and `detect_overdue_tasks` are
**deterministic** (no model in the scheduling decision) — deliberately keeping model decisions
separate from mechanical computation.

## 7. State Model

State is a typed LangGraph `TypedDict` ([app/agent/state.py](../app/agent/state.py)) that persists per
conversation `thread_id` via a checkpointer:

| Field | Purpose |
|---|---|
| `messages` | Conversation history (session memory); `add_messages` reducer appends |
| `referenced_tasks` | The last task list shown, in order — resolves "the second one" |
| `preferences` | Preferences stated during the session |
| `pending_approval` | The write awaiting approval (drives the approval UI) |
| `approval_decision` | approved/rejected — routes the approval node |
| `executed` | (tool, args) signatures → result, for duplicate/loop detection |
| `step_count` | Agent steps this run — enforces the max-step limit |
| `trace` | Per-tool record (name, args, ok, result/error) for the execution log |
| `run_id`, `final_outcome` | Correlate with the log; how the run ended |

Distinction: **conversation history** (messages) and **current workflow state** (step_count,
pending_approval, trace) are separate; **long-term memory** is the database (tasks, notes); the
**execution log** is the durable audit record.

## 8. Approval Model

Read vs write is a first-class property of every tool (`is_write` / `requires_approval` in the
registry). Before any write executes, the graph hits the **approval node**, which calls LangGraph
`interrupt()` and pauses — checkpointed — surfacing: proposed action, tool name, input arguments,
and expected effect. The user **Approves** (optionally editing arguments), **Rejects** (control
returns, nothing runs), or the write executes on approval. Because the gate is structural, approval
compliance does not depend on the model choosing to comply.

## 9. Error Strategy

All ten required failure modes are handled with clean, user-safe messages (no stack traces/secrets):
missing API key, invalid model response, invalid tool arguments (Pydantic `ValidationError`), unknown
task id (`TaskNotFoundError`), database failure, empty input, tool timeout (30 s), LLM API error
(mapped 401/403/429/timeout), unsupported request (declined), and repeated failed calls (retry ≤ 2,
then surfaced). Execution limits — **8 steps, 2 retries/tool, 30 s timeout, duplicate-call
detection** — prevent runaway loops. A model fallback chain (north-mini → nemotron → gemma) adds
resilience.

## 10. Security Considerations

Secrets live only in a git-ignored `.env`; the tool permission boundary and approval gate prevent
unilateral writes; Pydantic validation rejects malformed/hallucinated arguments; tool results are
treated as data, not instructions (prompt-injection posture); logs store operational metadata only.
Full analysis in [A7](A7_security_review.md).
