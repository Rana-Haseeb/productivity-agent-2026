# A7 · Security Review

Nine risks and their controls, covering the required areas: API-key protection, prompt injection,
tool permission boundaries, sensitive-data exposure, destructive actions, log privacy, database
access, input validation, rate limiting, and approval-bypass.

| # | Risk | Impact | Control(s) in this project | Residual / future |
|---|---|---|---|---|
| 1 | **API-key / secret leakage** | Stolen LLM or DB credentials | Secrets only in a **git-ignored `.env`** (and `WEEK3_PROJECT_MEMORY.md` is git-ignored too); nothing hard-coded; keys never logged or shown in the UI; `.env.example` holds placeholders | Rotate the DB password (it was shared in chat during setup); use a managed secret store in production |
| 2 | **Prompt injection via tool data / notes** | Malicious note text tells the agent to take an action | Tool results and stored content are treated as **data, not instructions**; the system prompt is version-controlled; writes still require human approval, so an injected "delete everything" cannot execute unilaterally | Add an explicit injection-detection eval suite (planned) |
| 3 | **Approval bypass (unilateral writes)** | Agent mutates/deletes data without consent | Approval is **structural**: every write tool carries `requires_approval`, and the graph routes to an `interrupt()` before execution — not a prompt instruction the model could ignore. Verified: DB unchanged while paused; reject executes nothing | Per-tool, per-user permission policies |
| 4 | **Destructive / irreversible actions** | Data loss, sent emails | No hard-delete exposed to the agent as a casual action; email is **simulated (drafted only)**, never sent; completing/updating tasks is reversible and approval-gated | Soft-delete + undo log |
| 5 | **Sensitive-data exposure in the UI** | Leaked internals/PII to the user or logs | UI shows short operational status only — **no chain-of-thought, no stack traces, no secrets**; errors are mapped to friendly messages | Redaction pass on any future PII fields |
| 6 | **Log privacy** | Logs leak keys or reasoning | Execution logs store **operational metadata only** (request, tools, args, results, outcome, timing) — explicitly **no API keys and no model reasoning** | Field-level access control on the logs table |
| 7 | **Unvalidated / hallucinated tool arguments** | Bad writes, injection, crashes | **Pydantic validates every tool argument**; bad/missing/hallucinated args raise a clean `ToolValidationError`; task ids are UUID-validated; all SQL uses **bound parameters** (no string interpolation) | Constrain free-text fields further |
| 8 | **Database access scope** | Over-privileged DB connection | Access only through the typed repository (no ad-hoc SQL from tools); connection via the session pooler | Use a **least-privilege** DB role instead of `postgres`; enable Row-Level Security for multi-user |
| 9 | **Denial of service / runaway cost / rate limits** | Infinite loops, quota exhaustion, cost blow-ups | **Execution limits**: max 8 steps, 2 retries/tool, 30 s tool timeout, duplicate-call & loop detection; LLM retry uses backoff; free-tier 50/day cap is documented and the graded run uses a paid model | Per-user rate limiting; budget alerts |

## Summary

The security posture rests on three pillars: **(1) secrets isolation** (nothing sensitive in code or
logs), **(2) a structural human-approval boundary** that no model output can bypass, and **(3) strict
typed validation** on every input and tool argument. The highest-priority follow-ups are rotating the
Supabase password, moving off the `postgres` superuser to a least-privilege role, and adding an
explicit prompt-injection regression suite.
