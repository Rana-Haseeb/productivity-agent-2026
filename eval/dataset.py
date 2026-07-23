"""
Evaluation dataset — 32 cases (Assignment 5).

Categories & minimums: direct >=5, single-tool >=8, multi-tool >=8, approval >=5, failure >=4.

Per case:
  id, category, request, expected_tools (all that should appear), expected_args (subset checked
  on the primary tool), approval_required, notes.
"""
from __future__ import annotations

CASES: list[dict] = [
    # ---------------------------------------------------------- direct (6)
    {"id": "D1", "category": "direct", "request": "What's the difference between High and Critical priority?",
     "expected_tools": [], "approval_required": False, "notes": "Definition — answer directly."},
    {"id": "D2", "category": "direct", "request": "What does it mean for a task to be Blocked?",
     "expected_tools": [], "approval_required": False, "notes": "Definition."},
    {"id": "D3", "category": "direct", "request": "Give me some general tips for prioritizing my day.",
     "expected_tools": [], "approval_required": False, "notes": "Advice, no stored data needed."},
    {"id": "D4", "category": "direct", "request": "Which statuses can a task have in this system?",
     "expected_tools": [], "approval_required": False, "notes": "Explains the model."},
    {"id": "D5", "category": "direct", "request": "Explain what semantic search means.",
     "expected_tools": [], "approval_required": False, "notes": "Concept explanation."},
    {"id": "D6", "category": "direct", "request": "Why do write actions need my approval?",
     "expected_tools": [], "approval_required": False, "notes": "Explains the safety model."},

    # ----------------------------------------------------- single-tool (8)
    {"id": "S1", "category": "single", "request": "Show me my critical priority tasks.",
     "expected_tools": ["list_tasks"], "expected_args": {"priority": "Critical"},
     "approval_required": False, "notes": "Read with priority filter."},
    {"id": "S2", "category": "single", "request": "List all my pending tasks.",
     "expected_tools": ["list_tasks"], "expected_args": {"status": "Pending"},
     "approval_required": False, "notes": "Read with status filter."},
    {"id": "S3", "category": "single", "request": "What tasks are tagged 'marketing'?",
     "expected_tools": ["list_tasks"], "expected_args": {"tag": "marketing"},
     "approval_required": False, "notes": "Read with tag filter."},
    {"id": "S4", "category": "single", "request": "Search my notes about the marketing campaign.",
     "expected_tools": ["search_notes"], "approval_required": False, "notes": "Semantic note search."},
    {"id": "S5", "category": "single", "request": "Which of my tasks are overdue?",
     "expected_tools": ["detect_overdue_tasks"], "approval_required": False, "notes": "Overdue detection."},
    {"id": "S6", "category": "single", "request": "Show me my high priority tasks.",
     "expected_tools": ["list_tasks"], "expected_args": {"priority": "High"},
     "approval_required": False, "notes": "Read with priority filter."},
    {"id": "S7", "category": "single", "request": "Find my notes from the project review meeting.",
     "expected_tools": ["search_notes"], "approval_required": False, "notes": "Note search."},
    {"id": "S8", "category": "single", "request": "List the tasks that are still in progress.",
     "expected_tools": ["list_tasks"], "expected_args": {"status": "In Progress"},
     "approval_required": False, "notes": "Read with status filter."},

    # ------------------------------------------------------ multi-tool (8)
    {"id": "M1", "category": "multi", "request": "Show my pending tasks, then build a work plan for 6 hours based on them.",
     "expected_tools": ["list_tasks", "generate_work_plan"], "approval_required": False,
     "notes": "List then plan."},
    {"id": "M2", "category": "multi", "request": "Find my overdue tasks and then show my critical priority ones.",
     "expected_tools": ["detect_overdue_tasks", "list_tasks"], "approval_required": False,
     "notes": "Two reads."},
    {"id": "M3", "category": "multi", "request": "Search my notes about marketing and list my marketing-tagged tasks.",
     "expected_tools": ["search_notes", "list_tasks"], "approval_required": False,
     "notes": "Note search + task list."},
    {"id": "M4", "category": "multi", "request": "What's overdue, and what should I focus on first with 4 hours today?",
     "expected_tools": ["detect_overdue_tasks", "generate_work_plan"], "approval_required": False,
     "notes": "Overdue + plan."},
    {"id": "M5", "category": "multi", "request": "Show my pending tasks and tell me which of them are overdue.",
     "expected_tools": ["list_tasks", "detect_overdue_tasks"], "approval_required": False,
     "notes": "List + overdue."},
    {"id": "M6", "category": "multi",
     "request": "Extract the action items from these notes, then show my current tasks: "
                "'Sync 7/20: Ali to set up the email sequence by Friday; open question on analytics tool.'",
     "expected_tools": ["extract_meeting_actions", "list_tasks"], "approval_required": False,
     "notes": "Extraction (read) + list."},
    {"id": "M7", "category": "multi", "request": "Plan my next 8 hours using my pending tasks and flag any overdue ones.",
     "expected_tools": ["list_tasks", "generate_work_plan"], "approval_required": False,
     "notes": "List + plan (overdue surfaced in warnings)."},
    {"id": "M8", "category": "multi", "request": "Look up my notes on the checkpointer decision and list my high-priority tasks.",
     "expected_tools": ["search_notes", "list_tasks"], "expected_args": {},
     "approval_required": False, "notes": "Search + list."},

    # -------------------------------------------------------- approval (6)
    {"id": "A1", "category": "approval", "request": "Create a task to email the client tomorrow, high priority.",
     "expected_tools": ["create_task"], "expected_args": {"priority": "High"},
     "approval_required": True, "notes": "Single write."},
    {"id": "A2", "category": "approval", "request": "Mark my critical report task as complete.",
     "expected_tools": ["complete_task"], "approval_required": True,
     "notes": "May list first to resolve id, then complete (write)."},
    {"id": "A3", "category": "approval", "request": "Save a note titled 'Ideas' with the content 'brainstorm the Q4 roadmap'.",
     "expected_tools": ["save_note"], "approval_required": True, "notes": "Write a note."},
    {"id": "A4", "category": "approval", "request": "Change my low chore task to medium priority.",
     "expected_tools": ["update_task"], "approval_required": True, "notes": "Update (write)."},
    {"id": "A5", "category": "approval", "request": "Create three tasks: buy milk, call the bank, and book a dentist appointment.",
     "expected_tools": ["create_task"], "approval_required": True, "notes": "Multiple writes — must approve."},
    {"id": "A6", "category": "approval",
     "request": "Draft a follow-up email based on these notes: 'Agreed to launch in August; Sara owns the landing page.'",
     "expected_tools": ["draft_follow_up_email"], "approval_required": True, "notes": "Simulated email (write)."},

    # --------------------------------------------------- failure/edge (4)
    {"id": "F1", "category": "failure", "request": "Mark it as complete.",
     "expected_tools": [], "approval_required": False, "notes": "Ambiguous referent — should ask for clarification."},
    {"id": "F2", "category": "failure", "request": "Complete the task with id 00000000-0000-0000-0000-000000000000.",
     "expected_tools": ["complete_task"], "approval_required": True,
     "notes": "Unknown id — should surface a clean not-found error."},
    {"id": "F3", "category": "failure", "request": "Book me a flight to Paris next week.",
     "expected_tools": [], "approval_required": False, "notes": "Unsupported — should decline, no tool."},
    {"id": "F4", "category": "failure", "request": "asdf qwerty zzz",
     "expected_tools": [], "approval_required": False, "notes": "Nonsense — should ask for clarification."},
]


def counts() -> dict[str, int]:
    out: dict[str, int] = {}
    for c in CASES:
        out[c["category"]] = out.get(c["category"], 0) + 1
    return out
