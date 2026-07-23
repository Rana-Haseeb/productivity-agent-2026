"""
Task tools — create, list, update, complete.

All four validate their inputs with Pydantic. The three write tools (create/update/complete)
are registered with ``requires_approval=True`` so the agent pauses before mutating data.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.database.models import Priority, Status, Task, TaskCreate, TaskFilter, TaskUpdate
from app.tools.registry import ToolContext, ToolError, register_tool


def validate_task_id(v: str) -> str:
    """Reusable validator: a task id must be a well-formed UUID string."""
    try:
        return str(uuid.UUID(str(v)))
    except (ValueError, AttributeError, TypeError):
        raise ValueError("must be a valid task id (UUID)")


class TaskSummary(BaseModel):
    """Compact task view returned by list/plan tools."""

    task_id: str
    title: str
    priority: Priority
    status: Status
    due_date: date | None = None
    tags: list[str] = Field(default_factory=list)

    @classmethod
    def from_task(cls, t: Task) -> "TaskSummary":
        return cls(
            task_id=str(t.id),
            title=t.title,
            priority=t.priority,
            status=t.status,
            due_date=t.due_date,
            tags=t.tags,
        )


# --------------------------------------------------------------- create_task
class CreateTaskInput(BaseModel):
    title: str = Field(..., min_length=1, max_length=300, description="Short task title.")
    description: str = Field("", description="Optional longer detail about the task.")
    priority: Priority = Field(Priority.MEDIUM, description="One of Low, Medium, High, Critical.")
    due_date: date | None = Field(None, description="Due date as YYYY-MM-DD, if any.")
    tags: list[str] = Field(default_factory=list, description="Optional labels, e.g. ['work'].")

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title must not be blank")
        return v.strip()


class CreateTaskOutput(BaseModel):
    task_id: str
    title: str
    priority: Priority
    status: Status
    confirmation: str


@register_tool(
    name="create_task",
    description=(
        "Create ONE new task and store it. Use when the user wants to add, track, or remember a "
        "to-do (e.g. 'add a task to email the client', 'remind me to file the report'). Provide a "
        "clear title; priority defaults to Medium and status to Pending. This is a WRITE action and "
        "requires approval. Do NOT use to list, find, or complete existing tasks."
    ),
    input_model=CreateTaskInput,
    output_model=CreateTaskOutput,
    is_write=True,
    requires_approval=True,
)
def create_task(inp: CreateTaskInput, ctx: ToolContext) -> CreateTaskOutput:
    task = ctx.repo.create_task(
        TaskCreate(
            title=inp.title,
            description=inp.description,
            priority=inp.priority,
            due_date=inp.due_date,
            tags=inp.tags,
        )
    )
    return CreateTaskOutput(
        task_id=str(task.id),
        title=task.title,
        priority=task.priority,
        status=task.status,
        confirmation=f"Created task '{task.title}' ({task.priority.value} priority).",
    )


# ---------------------------------------------------------------- list_tasks
class ListTasksInput(BaseModel):
    status: Status | None = Field(None, description="Filter by status.")
    priority: Priority | None = Field(None, description="Filter by priority.")
    tag: str | None = Field(None, description="Filter to tasks having this tag.")
    due_before: date | None = Field(None, description="Only tasks due on/before this date.")
    due_after: date | None = Field(None, description="Only tasks due on/after this date.")
    limit: int = Field(100, ge=1, le=500)


class ListTasksOutput(BaseModel):
    tasks: list[TaskSummary]
    total_count: int


@register_tool(
    name="list_tasks",
    description=(
        "List existing tasks, optionally filtered by status, priority, tag, or due-date range. Use "
        "for requests like 'show my high-priority tasks', 'what's due this week', 'list pending "
        "work'. This is READ-ONLY and never needs approval. Return the matching tasks and a count."
    ),
    input_model=ListTasksInput,
    output_model=ListTasksOutput,
    is_write=False,
    requires_approval=False,
)
def list_tasks(inp: ListTasksInput, ctx: ToolContext) -> ListTasksOutput:
    tasks = ctx.repo.list_tasks(
        TaskFilter(
            status=inp.status,
            priority=inp.priority,
            tag=inp.tag,
            due_before=inp.due_before,
            due_after=inp.due_after,
            limit=inp.limit,
        )
    )
    summaries = [TaskSummary.from_task(t) for t in tasks]
    return ListTasksOutput(tasks=summaries, total_count=len(summaries))


# --------------------------------------------------------------- update_task
class UpdateTaskInput(BaseModel):
    task_id: str = Field(..., description="ID of the task to update.")
    title: str | None = Field(None, max_length=300)
    description: str | None = None
    priority: Priority | None = None
    status: Status | None = None
    due_date: date | None = None
    tags: list[str] | None = None

    _v_id = field_validator("task_id")(validate_task_id)


class UpdateTaskOutput(BaseModel):
    task: TaskSummary
    confirmation: str


@register_tool(
    name="update_task",
    description=(
        "Update fields of an EXISTING task identified by task_id (title, description, priority, "
        "status, due date, tags). Use for 'change the priority to high', 'move the deadline', "
        "'mark it blocked'. Requires a valid task_id — call list_tasks first if you don't have it. "
        "WRITE action; requires approval. To mark a task done, prefer complete_task."
    ),
    input_model=UpdateTaskInput,
    output_model=UpdateTaskOutput,
    is_write=True,
    requires_approval=True,
)
def update_task(inp: UpdateTaskInput, ctx: ToolContext) -> UpdateTaskOutput:
    changes = inp.model_dump(exclude_unset=True, exclude_none=True)
    changes.pop("task_id", None)
    if not changes:
        raise ToolError("No fields provided to update.")
    task = ctx.repo.update_task(inp.task_id, TaskUpdate(**changes))
    return UpdateTaskOutput(
        task=TaskSummary.from_task(task),
        confirmation=f"Updated task '{task.title}'.",
    )


# ------------------------------------------------------------- complete_task
class CompleteTaskInput(BaseModel):
    task_id: str = Field(..., description="ID of the task to mark complete.")

    _v_id = field_validator("task_id")(validate_task_id)


class CompleteTaskOutput(BaseModel):
    task_id: str
    status: Status
    completed_at: datetime
    confirmation: str


@register_tool(
    name="complete_task",
    description=(
        "Mark an EXISTING task as Completed. Use for 'mark the website task done', 'complete the "
        "report task'. Requires a valid task_id — resolve it with list_tasks first if needed. This "
        "is a WRITE action and ALWAYS requires human approval before it runs."
    ),
    input_model=CompleteTaskInput,
    output_model=CompleteTaskOutput,
    is_write=True,
    requires_approval=True,
)
def complete_task(inp: CompleteTaskInput, ctx: ToolContext) -> CompleteTaskOutput:
    task = ctx.repo.complete_task(inp.task_id)
    return CompleteTaskOutput(
        task_id=str(task.id),
        status=task.status,
        completed_at=task.updated_date,
        confirmation=f"Marked '{task.title}' as Completed.",
    )
