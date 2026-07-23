# A4 · Tool Specification

Auto-generated from the tool registry and Pydantic schemas (`python scripts/gen_tool_spec.py`). Another developer can implement these tools from this spec alone.

| # | Tool | R/W | Approval |
|---|---|---|---|
| 1 | `search_notes` | read | — |
| 2 | `save_note` | write | ✅ |
| 3 | `create_task` | write | ✅ |
| 4 | `list_tasks` | read | — |
| 5 | `update_task` | write | ✅ |
| 6 | `complete_task` | write | ✅ |
| 7 | `extract_meeting_actions` | read | — |
| 8 | `generate_work_plan` | read | — |
| 9 | `detect_overdue_tasks` | read | — |
| 10 | `draft_follow_up_email` | write | ✅ |

## `search_notes`

**Purpose.** Search the user's saved notes and return the most relevant ones with a match score. Use for 'find my notes about the marketing campaign', 'what did I write about onboarding'. Semantic search (default) matches by meaning; set semantic=false for exact keyword match. READ-ONLY; no approval needed.

**Operation:** read · **Approval required:** no

**Input schema**

| Field | Type | Required |
|---|---|---|
| `query` | string | yes |
| `category` | string (optional) | no |
| `date_from` | string(date) (optional) | no |
| `date_to` | string(date) (optional) | no |
| `semantic` | boolean | no |
| `limit` | integer | no |

**Output schema**

| Field | Type |
|---|---|
| `matches` | array<NoteHit> |
| `count` | integer |

**Possible errors.** Empty query (ValidationError); database unavailable.

**Example call.** `{"query": "marketing budget", "semantic": true, "limit": 5}`

**Example result.** `{"matches": [{"note_id": "…", "title": "Marketing", "snippet": "…", "score": 0.62}], "count": 1}`

## `save_note`

**Purpose.** Save a NEW note (title + content, optional category and tags) so it can be searched later. Use for 'save this as a note', 'remember that ...'. Its embedding is computed automatically for semantic search. WRITE action; requires approval. Do NOT use to create actionable tasks — use create_task for those.

**Operation:** write · **Approval required:** yes

**Input schema**

| Field | Type | Required |
|---|---|---|
| `title` | string | yes |
| `content` | string | yes |
| `category` | string | no |
| `tags` | array<string> | no |

**Output schema**

| Field | Type |
|---|---|
| `note_id` | string |
| `title` | string |
| `confirmation` | string |

**Possible errors.** Blank title/content (ValidationError); database unavailable.

**Example call.** `{"title": "Ideas", "content": "brainstorm Q4", "category": "idea"}`

**Example result.** `{"note_id": "…", "title": "Ideas", "confirmation": "Saved note …"}`

## `create_task`

**Purpose.** Create ONE new task and store it. Use when the user wants to add, track, or remember a to-do (e.g. 'add a task to email the client', 'remind me to file the report'). Provide a clear title; priority defaults to Medium and status to Pending. This is a WRITE action and requires approval. Do NOT use to list, find, or complete existing tasks.

**Operation:** write · **Approval required:** yes

**Input schema**

| Field | Type | Required |
|---|---|---|
| `title` | string | yes |
| `description` | string | no |
| `priority` | enum['Low', 'Medium', 'High', 'Critical'] | no |
| `due_date` | string(date) (optional) | no |
| `tags` | array<string> | no |

**Output schema**

| Field | Type |
|---|---|
| `task_id` | string |
| `title` | string |
| `priority` | enum['Low', 'Medium', 'High', 'Critical'] |
| `status` | enum['Pending', 'In Progress', 'Blocked', 'Completed', 'Cancelled'] |
| `confirmation` | string |

**Possible errors.** Invalid/blank title (ValidationError); database unavailable.

**Example call.** `{"title": "Email the client", "priority": "High", "due_date": "2026-07-25"}`

**Example result.** `{"task_id": "…", "title": "Email the client", "priority": "High", "status": "Pending", "confirmation": "Created task …"}`

## `list_tasks`

**Purpose.** List existing tasks, optionally filtered by status, priority, tag, or due-date range. Use for requests like 'show my high-priority tasks', 'what's due this week', 'list pending work'. This is READ-ONLY and never needs approval. Return the matching tasks and a count.

**Operation:** read · **Approval required:** no

**Input schema**

| Field | Type | Required |
|---|---|---|
| `status` | enum['Pending', 'In Progress', 'Blocked', 'Completed', 'Cancelled'] (optional) | no |
| `priority` | enum['Low', 'Medium', 'High', 'Critical'] (optional) | no |
| `tag` | string (optional) | no |
| `due_before` | string(date) (optional) | no |
| `due_after` | string(date) (optional) | no |
| `limit` | integer | no |

**Output schema**

| Field | Type |
|---|---|
| `tasks` | array<TaskSummary> |
| `total_count` | integer |

**Possible errors.** Invalid filter value (ValidationError); database unavailable.

**Example call.** `{"priority": "Critical", "status": "Pending"}`

**Example result.** `{"tasks": [{"task_id": "…", "title": "…", "priority": "Critical", "status": "Pending"}], "total_count": 1}`

## `update_task`

**Purpose.** Update fields of an EXISTING task identified by task_id (title, description, priority, status, due date, tags). Use for 'change the priority to high', 'move the deadline', 'mark it blocked'. Requires a valid task_id — call list_tasks first if you don't have it. WRITE action; requires approval. To mark a task done, prefer complete_task.

**Operation:** write · **Approval required:** yes

**Input schema**

| Field | Type | Required |
|---|---|---|
| `task_id` | string | yes |
| `title` | string (optional) | no |
| `description` | string (optional) | no |
| `priority` | enum['Low', 'Medium', 'High', 'Critical'] (optional) | no |
| `status` | enum['Pending', 'In Progress', 'Blocked', 'Completed', 'Cancelled'] (optional) | no |
| `due_date` | string(date) (optional) | no |
| `tags` | array<string> (optional) | no |

**Output schema**

| Field | Type |
|---|---|
| `task` | TaskSummary |
| `confirmation` | string |

**Possible errors.** Invalid task_id (ValidationError); unknown task (TaskNotFoundError); no fields given.

**Example call.** `{"task_id": "…", "priority": "Low"}`

**Example result.** `{"task": {"task_id": "…", "priority": "Low", …}, "confirmation": "Updated task …"}`

## `complete_task`

**Purpose.** Mark an EXISTING task as Completed. Use for 'mark the website task done', 'complete the report task'. Requires a valid task_id — resolve it with list_tasks first if needed. This is a WRITE action and ALWAYS requires human approval before it runs.

**Operation:** write · **Approval required:** yes

**Input schema**

| Field | Type | Required |
|---|---|---|
| `task_id` | string | yes |

**Output schema**

| Field | Type |
|---|---|
| `task_id` | string |
| `status` | enum['Pending', 'In Progress', 'Blocked', 'Completed', 'Cancelled'] |
| `completed_at` | string(date-time) |
| `confirmation` | string |

**Possible errors.** Invalid task_id (ValidationError); unknown task (TaskNotFoundError).

**Example call.** `{"task_id": "…"}`

**Example result.** `{"task_id": "…", "status": "Completed", "completed_at": "2026-07-23T…", "confirmation": "Marked … Completed."}`

## `extract_meeting_actions`

**Purpose.** Analyze meeting notes or a transcript and return a STRUCTURED breakdown: summary, decisions, action items (with owners/deadlines when stated), and unresolved questions. Use when the user pastes notes and wants them organized or wants action items identified. READ/COMPUTE only — it does NOT create tasks. To turn the action items into tasks, call create_task afterwards (which requires approval).

**Operation:** read · **Approval required:** no

**Input schema**

| Field | Type | Required |
|---|---|---|
| `meeting_notes` | string | yes |

**Output schema**

| Field | Type |
|---|---|
| `summary` | string |
| `decisions` | array<string> |
| `action_items` | array<ActionItem> |
| `unresolved_questions` | array<string> |

**Possible errors.** Empty notes (ValidationError); LLM empty/invalid response (LLMError).

**Example call.** `{"meeting_notes": "Sara owns the landing page by 7/28…"}`

**Example result.** `{"summary": "…", "decisions": ["…"], "action_items": [{"description": "…", "owner": "Sara", "deadline": "7/28"}], "unresolved_questions": ["…"]}`

## `generate_work_plan`

**Purpose.** Build an ordered day plan from the user's active tasks, fitting them into the available hours. Ranks by priority and deadline urgency (overdue first), estimates effort, and lists what to defer plus risk warnings. Use for 'plan my day', 'what should I work on with 6 hours'. READ/COMPUTE only; no approval needed. Scheduling is deterministic — not left to the model.

**Operation:** read · **Approval required:** no

**Input schema**

| Field | Type | Required |
|---|---|---|
| `available_hours` | number | no |
| `date` | string(date) (optional) | no |
| `user_priorities` | array<string> | no |

**Output schema**

| Field | Type |
|---|---|
| `plan_date` | string(date) |
| `ordered_schedule` | array<ScheduledItem> |
| `focus_areas` | array<string> |
| `deferred_tasks` | array<TaskSummary> |
| `risk_warnings` | array<string> |
| `total_scheduled_hours` | number |

**Possible errors.** available_hours out of range (ValidationError). Empty task list → empty plan.

**Example call.** `{"available_hours": 6, "user_priorities": ["marketing"]}`

**Example result.** `{"plan_date": "2026-07-23", "ordered_schedule": [{"title": "…", "est_hours": 3, "reason": "Critical; due in 3 days"}], "deferred_tasks": [], "risk_warnings": [], "total_scheduled_hours": 5.5}`

## `detect_overdue_tasks`

**Purpose.** Find all active tasks whose due date has passed, sorted by how overdue and how important they are, and recommend what to tackle first. Use for 'what's overdue', 'am I behind on anything'. READ-ONLY; no approval needed.

**Operation:** read · **Approval required:** no

**Input schema**

| Field | Type | Required |
|---|---|---|
| `as_of` | string(date) (optional) | no |

**Output schema**

| Field | Type |
|---|---|
| `overdue_tasks` | array<OverdueTaskItem> |
| `count` | integer |
| `recommendation` | string |

**Possible errors.** None typical (returns empty list when nothing is overdue).

**Example call.** `{}`

**Example result.** `{"overdue_tasks": [{"title": "…", "days_overdue": 2}], "count": 1, "recommendation": "Start with …"}`

## `draft_follow_up_email`

**Purpose.** Draft a follow-up email based on meeting notes or a summary, in the requested tone. Returns a subject and body for review. Use for 'draft a follow-up email from these notes'. This is a WRITE/irreversible-style action (a message to be sent) and requires approval; sending is SIMULATED — the email is never actually delivered.

**Operation:** write · **Approval required:** yes

**Input schema**

| Field | Type | Required |
|---|---|---|
| `context` | string | yes |
| `recipient` | string (optional) | no |
| `tone` | string | no |

**Output schema**

| Field | Type |
|---|---|
| `to` | string (optional) |
| `subject` | string |
| `body` | string |
| `note` | string |

**Possible errors.** Empty context (ValidationError); LLM error (LLMError).

**Example call.** `{"context": "Agreed to launch in August…", "recipient": "team@co.com", "tone": "professional"}`

**Example result.** `{"to": "team@co.com", "subject": "…", "body": "…", "note": "Simulated draft — not actually sent."}`
