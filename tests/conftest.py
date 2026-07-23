"""
Shared test fixtures.

Tests run WITHOUT a database or network: a ``FakeRepo`` holds data in memory and a ``FakeLLM``
returns scripted tool calls. This keeps the suite fast and deterministic (no API keys, no torch,
no Supabase). The one real-DB test lives in ``test_persistence.py`` and skips if unreachable.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from langchain_core.messages import AIMessage

from app.database.models import (
    Note,
    NoteCreate,
    NoteMatch,
    Priority,
    Status,
    Task,
    TaskCreate,
    TaskFilter,
    TaskUpdate,
)
from app.database.repository import TaskNotFoundError
from app.tools import ToolContext


# ------------------------------------------------------------------ fake repo
class FakeRepo:
    """In-memory stand-in for Repository with the same method surface."""

    def __init__(self):
        self._tasks: dict[str, Task] = {}
        self._notes: dict[str, Note] = {}
        self._logs: list = []

    # tasks
    def create_task(self, data: TaskCreate) -> Task:
        now = datetime.now()
        t = Task(
            id=uuid.uuid4(), title=data.title, description=data.description,
            priority=data.priority, status=Status.PENDING, due_date=data.due_date,
            tags=data.tags, source=data.source, notes=data.notes,
            created_date=now, updated_date=now,
        )
        self._tasks[str(t.id)] = t
        return t

    def get_task(self, task_id) -> Task:
        t = self._tasks.get(str(task_id))
        if t is None:
            raise TaskNotFoundError(task_id)
        return t

    def list_tasks(self, flt: TaskFilter | None = None) -> list[Task]:
        flt = flt or TaskFilter()
        out = list(self._tasks.values())
        if flt.status is not None:
            out = [t for t in out if t.status == flt.status]
        if flt.priority is not None:
            out = [t for t in out if t.priority == flt.priority]
        if flt.tag is not None:
            out = [t for t in out if flt.tag in t.tags]
        if flt.due_before is not None:
            out = [t for t in out if t.due_date and t.due_date <= flt.due_before]
        if flt.due_after is not None:
            out = [t for t in out if t.due_date and t.due_date >= flt.due_after]
        return out[: flt.limit]

    def update_task(self, task_id, data: TaskUpdate) -> Task:
        t = self.get_task(task_id)
        changes = data.changed_fields()
        updated = t.model_copy(update={**changes, "updated_date": datetime.now()})
        self._tasks[str(task_id)] = updated
        return updated

    def complete_task(self, task_id) -> Task:
        t = self.get_task(task_id)
        updated = t.model_copy(update={"status": Status.COMPLETED, "updated_date": datetime.now()})
        self._tasks[str(task_id)] = updated
        return updated

    def delete_task(self, task_id) -> bool:
        return self._tasks.pop(str(task_id), None) is not None

    # notes
    def save_note(self, data: NoteCreate) -> Note:
        now = datetime.now()
        n = Note(id=uuid.uuid4(), title=data.title, content=data.content,
                 category=data.category, tags=data.tags, created_date=now, updated_date=now)
        self._notes[str(n.id)] = n
        return n

    def search_notes_semantic(self, query, k=5, category=None, date_from=None, date_to=None):
        return self._match_notes(query, k, category)

    def search_notes_keyword(self, query, k=5):
        return self._match_notes(query, k, None)

    def _match_notes(self, query, k, category):
        q = (query or "").lower()
        hits = []
        for n in self._notes.values():
            if category and n.category != category:
                continue
            text = f"{n.title} {n.content}".lower()
            score = 1.0 if not q else (sum(w in text for w in q.split()) / max(1, len(q.split())))
            if not q or score > 0:
                hits.append(NoteMatch(note=n, score=round(float(score), 3)))
        hits.sort(key=lambda m: m.score, reverse=True)
        return hits[:k]

    # logs
    def save_execution_log(self, log):
        self._logs.append(log)
        return log.run_id

    def list_execution_logs(self, limit=50):
        return self._logs[-limit:]

    def ping(self):
        return True


# ------------------------------------------------------------------- fake llm
def ai_tool(name: str, args: dict) -> tuple:
    return ("tool", name, args)


def ai_final(text: str) -> tuple:
    return ("final", text)


def _build_message(spec: tuple) -> AIMessage:
    if spec[0] == "final":
        return AIMessage(content=spec[1])
    _, name, args = spec
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": f"call_{uuid.uuid4().hex[:8]}",
                     "type": "tool_call"}],
    )


class FakeLLM:
    """Scripted LLM. ``specs`` is a list of ai_tool(...)/ai_final(...) entries; the last repeats."""

    def __init__(self, specs: list[tuple], structured_factory=None):
        self.specs = specs
        self.i = 0
        self.last_used_model = "fake-model"
        self._structured_factory = structured_factory

    def invoke_tools(self, messages, tools):
        spec = self.specs[min(self.i, len(self.specs) - 1)]
        self.i += 1
        return _build_message(spec)

    def structured(self, system, user, schema):
        if self._structured_factory:
            return self._structured_factory(schema)
        raise NotImplementedError("no structured_factory provided")


# -------------------------------------------------------------------- fixtures
@pytest.fixture
def fake_repo() -> FakeRepo:
    return FakeRepo()


@pytest.fixture
def seeded_repo(fake_repo) -> FakeRepo:
    from datetime import date, timedelta

    today = date.today()
    fake_repo.create_task(TaskCreate(title="Critical report", priority=Priority.CRITICAL,
                                     due_date=today + timedelta(days=1), tags=["work"]))
    fake_repo.create_task(TaskCreate(title="Low chore", priority=Priority.LOW))
    fake_repo.create_task(TaskCreate(title="Overdue thing", priority=Priority.HIGH,
                                     due_date=today - timedelta(days=3)))
    fake_repo.save_note(NoteCreate(title="Marketing", content="Campaign budget is 12k", category="mkt"))
    return fake_repo


@pytest.fixture
def ctx(fake_repo) -> ToolContext:
    return ToolContext(repo=fake_repo, llm=None)
