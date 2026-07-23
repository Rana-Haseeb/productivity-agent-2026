"""
Pydantic models for the data layer.

Two flavours per entity:
- Full read models (``Task``, ``Note``, ``ExecutionLog``) mirror a database row.
- Create/Update DTOs carry only the fields a caller may set, with validation.

These are the single source of truth for shapes flowing between the repository,
the tools, and the agent.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


# --------------------------------------------------------------------- enums
class Priority(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class Status(str, Enum):
    PENDING = "Pending"
    IN_PROGRESS = "In Progress"
    BLOCKED = "Blocked"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"


# --------------------------------------------------------------------- tasks
class TaskCreate(BaseModel):
    """Fields accepted when creating a task."""

    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    priority: Priority = Priority.MEDIUM
    due_date: date | None = None
    tags: list[str] = Field(default_factory=list)
    source: str = "user"
    notes: str = ""

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title must not be blank")
        return v.strip()


class TaskUpdate(BaseModel):
    """Partial update — only provided fields are changed."""

    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    priority: Priority | None = None
    status: Status | None = None
    due_date: date | None = None
    tags: list[str] | None = None
    notes: str | None = None

    def changed_fields(self) -> dict:
        """Only the fields the caller actually set (excludes unset + None)."""
        return self.model_dump(exclude_unset=True, exclude_none=True)


class Task(BaseModel):
    """A task as stored in the database."""

    id: uuid.UUID
    title: str
    description: str = ""
    priority: Priority
    status: Status
    due_date: date | None = None
    tags: list[str] = Field(default_factory=list)
    source: str = "user"
    notes: str = ""
    created_date: datetime
    updated_date: datetime


# --------------------------------------------------------------------- notes
class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1)
    category: str = "general"
    tags: list[str] = Field(default_factory=list)

    @field_validator("title", "content")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


class Note(BaseModel):
    id: uuid.UUID
    title: str
    content: str
    category: str = "general"
    tags: list[str] = Field(default_factory=list)
    created_date: datetime
    updated_date: datetime


class NoteMatch(BaseModel):
    """A note returned from search, with its relevance score (0..1, higher = closer)."""

    note: Note
    score: float


# ----------------------------------------------------------------- filters
class TaskFilter(BaseModel):
    """Filters for listing tasks; all optional (None = no filter)."""

    status: Status | None = None
    priority: Priority | None = None
    tag: str | None = None
    due_before: date | None = None
    due_after: date | None = None
    limit: int = 100


# --------------------------------------------------------------- exec logs
class ExecutionLog(BaseModel):
    """One agent run. Never stores API keys or chain-of-thought."""

    run_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    user_request: str
    model: str | None = None
    tools_called: list[str] = Field(default_factory=list)
    tool_args: list[dict] = Field(default_factory=list)
    tool_results: list[dict] = Field(default_factory=list)
    approval_status: str | None = None
    errors: list[str] = Field(default_factory=list)
    start_time: datetime = Field(default_factory=datetime.utcnow)
    end_time: datetime | None = None
    duration_ms: int | None = None
    final_outcome: str | None = None
