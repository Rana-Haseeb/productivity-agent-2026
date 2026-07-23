"""
Generate docs/A4_tool_specification.md from the live tool registry + Pydantic schemas.

Keeps the spec accurate and in sync with the code. Curated example calls/results and error
lists live here; everything else is derived from the models.

  python scripts/gen_tool_spec.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tools import all_specs  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "docs" / "A4_tool_specification.md"

ERRORS = {
    "create_task": "Invalid/blank title (ValidationError); database unavailable.",
    "list_tasks": "Invalid filter value (ValidationError); database unavailable.",
    "update_task": "Invalid task_id (ValidationError); unknown task (TaskNotFoundError); no fields given.",
    "complete_task": "Invalid task_id (ValidationError); unknown task (TaskNotFoundError).",
    "search_notes": "Empty query (ValidationError); database unavailable.",
    "save_note": "Blank title/content (ValidationError); database unavailable.",
    "extract_meeting_actions": "Empty notes (ValidationError); LLM empty/invalid response (LLMError).",
    "generate_work_plan": "available_hours out of range (ValidationError). Empty task list → empty plan.",
    "detect_overdue_tasks": "None typical (returns empty list when nothing is overdue).",
    "draft_follow_up_email": "Empty context (ValidationError); LLM error (LLMError).",
}

EXAMPLES = {
    "create_task": ('{"title": "Email the client", "priority": "High", "due_date": "2026-07-25"}',
                    '{"task_id": "…", "title": "Email the client", "priority": "High", "status": "Pending", "confirmation": "Created task …"}'),
    "list_tasks": ('{"priority": "Critical", "status": "Pending"}',
                   '{"tasks": [{"task_id": "…", "title": "…", "priority": "Critical", "status": "Pending"}], "total_count": 1}'),
    "update_task": ('{"task_id": "…", "priority": "Low"}',
                    '{"task": {"task_id": "…", "priority": "Low", …}, "confirmation": "Updated task …"}'),
    "complete_task": ('{"task_id": "…"}',
                      '{"task_id": "…", "status": "Completed", "completed_at": "2026-07-23T…", "confirmation": "Marked … Completed."}'),
    "search_notes": ('{"query": "marketing budget", "semantic": true, "limit": 5}',
                     '{"matches": [{"note_id": "…", "title": "Marketing", "snippet": "…", "score": 0.62}], "count": 1}'),
    "save_note": ('{"title": "Ideas", "content": "brainstorm Q4", "category": "idea"}',
                  '{"note_id": "…", "title": "Ideas", "confirmation": "Saved note …"}'),
    "extract_meeting_actions": ('{"meeting_notes": "Sara owns the landing page by 7/28…"}',
                                '{"summary": "…", "decisions": ["…"], "action_items": [{"description": "…", "owner": "Sara", "deadline": "7/28"}], "unresolved_questions": ["…"]}'),
    "generate_work_plan": ('{"available_hours": 6, "user_priorities": ["marketing"]}',
                           '{"plan_date": "2026-07-23", "ordered_schedule": [{"title": "…", "est_hours": 3, "reason": "Critical; due in 3 days"}], "deferred_tasks": [], "risk_warnings": [], "total_scheduled_hours": 5.5}'),
    "detect_overdue_tasks": ('{}',
                             '{"overdue_tasks": [{"title": "…", "days_overdue": 2}], "count": 1, "recommendation": "Start with …"}'),
    "draft_follow_up_email": ('{"context": "Agreed to launch in August…", "recipient": "team@co.com", "tone": "professional"}',
                              '{"to": "team@co.com", "subject": "…", "body": "…", "note": "Simulated draft — not actually sent."}'),
}


def _type(prop: dict, defs: dict) -> str:
    if "$ref" in prop:
        name = prop["$ref"].split("/")[-1]
        d = defs.get(name, {})
        return f"enum{d['enum']}" if "enum" in d else name
    if "anyOf" in prop:
        parts = [_type(p, defs) for p in prop["anyOf"] if p.get("type") != "null"]
        return "/".join(parts) + " (optional)"
    if prop.get("type") == "array":
        return f"array<{_type(prop.get('items', {}), defs)}>"
    if "type" in prop:
        return f"{prop['type']}({prop['format']})" if prop.get("format") else prop["type"]
    return "any"


def _fields(model) -> list[tuple[str, str, bool]]:
    schema = model.model_json_schema()
    defs = schema.get("$defs", {})
    required = set(schema.get("required", []))
    out = []
    for name, prop in schema.get("properties", {}).items():
        out.append((name, _type(prop, defs), name in required))
    return out


def render() -> str:
    lines = [
        "# A4 · Tool Specification",
        "",
        "Auto-generated from the tool registry and Pydantic schemas "
        "(`python scripts/gen_tool_spec.py`). Another developer can implement these tools from this "
        "spec alone.",
        "",
        "| # | Tool | R/W | Approval |",
        "|---|---|---|---|",
    ]
    for i, s in enumerate(all_specs(), 1):
        lines.append(f"| {i} | `{s.name}` | {'write' if s.is_write else 'read'} | "
                     f"{'✅' if s.requires_approval else '—'} |")
    lines.append("")

    for s in all_specs():
        call, result = EXAMPLES.get(s.name, ("—", "—"))
        lines += [
            f"## `{s.name}`",
            "",
            f"**Purpose.** {s.description}",
            "",
            f"**Operation:** {'write' if s.is_write else 'read'} · "
            f"**Approval required:** {'yes' if s.requires_approval else 'no'}",
            "",
            "**Input schema**",
            "",
            "| Field | Type | Required |",
            "|---|---|---|",
        ]
        for name, typ, req in _fields(s.input_model):
            lines.append(f"| `{name}` | {typ} | {'yes' if req else 'no'} |")
        lines += ["", "**Output schema**", "", "| Field | Type |", "|---|---|"]
        for name, typ, _ in _fields(s.output_model):
            lines.append(f"| `{name}` | {typ} |")
        lines += [
            "",
            f"**Possible errors.** {ERRORS.get(s.name, '—')}",
            "",
            f"**Example call.** `{call}`",
            "",
            f"**Example result.** `{result}`",
            "",
        ]
    return "\n".join(lines)


if __name__ == "__main__":
    OUT.write_text(render(), encoding="utf-8")
    print(f"Wrote {OUT}")
