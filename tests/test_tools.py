"""Tool tests — creation, listing, updates, invalid id, notes, extraction, validation."""
from __future__ import annotations

import uuid

import pytest

from app.database.models import Priority, Status
from app.database.repository import TaskNotFoundError
from app.tools import ToolContext, ToolValidationError, run_tool
from app.tools.planning_tools import ExtractMeetingActionsOutput


# --------------------------------------------------------------- task tools
def test_create_task(ctx):
    out = run_tool("create_task", {"title": "Write report", "priority": "High"}, ctx)
    assert out.task_id
    assert out.priority == Priority.HIGH
    assert out.status == Status.PENDING
    assert ctx.repo.get_task(out.task_id).title == "Write report"


def test_list_tasks_and_filter(seeded_repo):
    ctx = ToolContext(repo=seeded_repo, llm=None)
    all_out = run_tool("list_tasks", {}, ctx)
    assert all_out.total_count == 3
    crit = run_tool("list_tasks", {"priority": "Critical"}, ctx)
    assert crit.total_count == 1
    assert crit.tasks[0].title == "Critical report"


def test_update_task(ctx):
    created = run_tool("create_task", {"title": "T", "priority": "Low"}, ctx)
    upd = run_tool("update_task", {"task_id": created.task_id, "priority": "Critical",
                                   "status": "In Progress"}, ctx)
    assert upd.task.priority == Priority.CRITICAL
    assert upd.task.status == Status.IN_PROGRESS


def test_complete_task(ctx):
    created = run_tool("create_task", {"title": "Finish", "priority": "Medium"}, ctx)
    done = run_tool("complete_task", {"task_id": created.task_id}, ctx)
    assert done.status == Status.COMPLETED
    assert done.completed_at is not None


def test_update_unknown_task_id_raises(ctx):
    with pytest.raises(TaskNotFoundError):
        run_tool("update_task", {"task_id": str(uuid.uuid4()), "priority": "High"}, ctx)


def test_invalid_task_id_rejected(ctx):
    with pytest.raises(ToolValidationError):
        run_tool("complete_task", {"task_id": "not-a-uuid"}, ctx)


def test_tool_input_validation_missing_title(ctx):
    with pytest.raises(ToolValidationError):
        run_tool("create_task", {"priority": "High"}, ctx)  # no title


# --------------------------------------------------------------- note tools
def test_save_and_search_notes(ctx):
    run_tool("save_note", {"title": "Marketing plan", "content": "Budget is 12k for Q3"}, ctx)
    hits = run_tool("search_notes", {"query": "budget", "semantic": False}, ctx)
    assert hits.count >= 1
    assert any("Marketing" in h.title for h in hits.matches)


# ---------------------------------------------------------- planning tools
def test_extract_meeting_actions_structured(fake_repo):
    def factory(schema):
        return schema(
            summary="Team synced on Q3.",
            decisions=["Launch in August"],
            action_items=[{"description": "Prepare landing page", "owner": "Sara"}],
            unresolved_questions=["Which analytics tool?"],
        )

    from tests.conftest import FakeLLM

    ctx = ToolContext(repo=fake_repo, llm=FakeLLM([], structured_factory=factory))
    out = run_tool("extract_meeting_actions", {"meeting_notes": "notes..."}, ctx)
    assert isinstance(out, ExtractMeetingActionsOutput)
    assert out.action_items[0].owner == "Sara"
    assert out.decisions == ["Launch in August"]


def test_generate_work_plan_orders_by_priority(seeded_repo):
    ctx = ToolContext(repo=seeded_repo, llm=None)
    plan = run_tool("generate_work_plan", {"available_hours": 8}, ctx)
    titles = [i.title for i in plan.ordered_schedule]
    # Overdue High and Critical should be scheduled; Low may defer under tight hours.
    assert "Critical report" in titles
    assert plan.total_scheduled_hours <= 8


def test_detect_overdue_tasks(seeded_repo):
    ctx = ToolContext(repo=seeded_repo, llm=None)
    out = run_tool("detect_overdue_tasks", {}, ctx)
    assert out.count == 1
    assert "Overdue thing" in out.recommendation
