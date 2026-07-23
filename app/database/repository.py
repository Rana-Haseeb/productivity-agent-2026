"""
Repository — all database access lives here (Supabase Postgres + pgvector).

Design choices:
- **One connection per operation** via ``_connect()``. Short-lived connections are robust
  against Streamlit's script reruns and the Supabase pooler handles them well.
- **Typed in/out**: methods accept and return the Pydantic models in ``models.py``; callers
  never touch raw rows or SQL.
- **No SQL injection surface**: every value is passed as a bound parameter.
- Raises :class:`TaskNotFoundError` for unknown ids so tools/agent can report a clean message
  (Requirement 8) instead of leaking a stack trace.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.config import settings
from app.database.models import (
    ExecutionLog,
    Note,
    NoteCreate,
    NoteMatch,
    Task,
    TaskCreate,
    TaskFilter,
    TaskUpdate,
)
from app.services.embeddings import embed

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


# --------------------------------------------------------------------- errors
class RepositoryError(RuntimeError):
    """Generic data-layer failure (connection, query, etc.)."""


class TaskNotFoundError(RepositoryError):
    def __init__(self, task_id: uuid.UUID | str):
        super().__init__(f"No task found with id {task_id}")
        self.task_id = task_id


class NoteNotFoundError(RepositoryError):
    def __init__(self, note_id: uuid.UUID | str):
        super().__init__(f"No note found with id {note_id}")
        self.note_id = note_id


class Repository:
    """Thin, typed wrapper over the database. Inject a ``dsn`` in tests."""

    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or settings.database_url
        if not self.dsn:
            raise RepositoryError(
                "DATABASE_URL is not set. Add the Supabase session-pooler string to your .env."
            )

    # ---------------------------------------------------------- connection
    @contextmanager
    def _connect(self, *, with_vector: bool = True) -> Iterator[psycopg.Connection]:
        try:
            conn = psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=15)
        except Exception as e:  # noqa: BLE001
            raise RepositoryError(f"Could not connect to the database: {e}") from e
        try:
            if with_vector:
                register_vector(conn)  # enables passing/receiving numpy vectors
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------- schema
    def init_schema(self) -> None:
        """Create tables, enums, triggers, and indexes (idempotent)."""
        sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        # vector type may not exist yet on first run → don't register it here.
        with self._connect(with_vector=False) as conn:
            conn.execute(sql)

    def ping(self) -> bool:
        """Return True if the database is reachable."""
        with self._connect(with_vector=False) as conn:
            return conn.execute("select 1").fetchone() is not None

    # -------------------------------------------------------------- tasks
    def create_task(self, data: TaskCreate) -> Task:
        row = self._one(
            """
            insert into tasks (title, description, priority, status, due_date, tags, source, notes)
            values (%s, %s, %s, 'Pending', %s, %s, %s, %s)
            returning *;
            """,
            (
                data.title,
                data.description,
                data.priority.value,
                data.due_date,
                data.tags,
                data.source,
                data.notes,
            ),
        )
        return Task.model_validate(row)

    def get_task(self, task_id: uuid.UUID | str) -> Task:
        row = self._maybe_one("select * from tasks where id = %s;", (str(task_id),))
        if row is None:
            raise TaskNotFoundError(task_id)
        return Task.model_validate(row)

    def list_tasks(self, flt: TaskFilter | None = None) -> list[Task]:
        flt = flt or TaskFilter()
        where: list[str] = []
        params: list = []
        if flt.status is not None:
            where.append("status = %s")
            params.append(flt.status.value)
        if flt.priority is not None:
            where.append("priority = %s")
            params.append(flt.priority.value)
        if flt.tag is not None:
            where.append("%s = any(tags)")
            params.append(flt.tag)
        if flt.due_before is not None:
            where.append("due_date <= %s")
            params.append(flt.due_before)
        if flt.due_after is not None:
            where.append("due_date >= %s")
            params.append(flt.due_after)
        clause = (" where " + " and ".join(where)) if where else ""
        params.append(flt.limit)
        rows = self._many(
            f"select * from tasks{clause} order by created_date desc limit %s;", tuple(params)
        )
        return [Task.model_validate(r) for r in rows]

    def update_task(self, task_id: uuid.UUID | str, data: TaskUpdate) -> Task:
        changes = data.changed_fields()
        if not changes:
            return self.get_task(task_id)  # nothing to change
        sets, params = [], []
        for field, value in changes.items():
            if field in {"priority", "status"} and hasattr(value, "value"):
                value = value.value
            sets.append(f"{field} = %s")
            params.append(value)
        params.append(str(task_id))
        row = self._maybe_one(
            f"update tasks set {', '.join(sets)} where id = %s returning *;", tuple(params)
        )
        if row is None:
            raise TaskNotFoundError(task_id)
        return Task.model_validate(row)

    def complete_task(self, task_id: uuid.UUID | str) -> Task:
        row = self._maybe_one(
            "update tasks set status = 'Completed' where id = %s returning *;", (str(task_id),)
        )
        if row is None:
            raise TaskNotFoundError(task_id)
        return Task.model_validate(row)

    def delete_task(self, task_id: uuid.UUID | str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("delete from tasks where id = %s;", (str(task_id),))
            return cur.rowcount > 0

    # -------------------------------------------------------------- notes
    def save_note(self, data: NoteCreate) -> Note:
        try:
            vector = embed(f"{data.title}\n{data.content}")
        except Exception:  # noqa: BLE001 — embeddings unavailable (e.g. torch not installed) → store NULL
            vector = None
        row = self._one(
            """
            insert into notes (title, content, category, tags, embedding)
            values (%s, %s, %s, %s, %s)
            returning id, title, content, category, tags, created_date, updated_date;
            """,
            (data.title, data.content, data.category, data.tags, vector),
        )
        return Note.model_validate(row)

    def search_notes_semantic(
        self,
        query: str,
        k: int = 5,
        category: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[NoteMatch]:
        """Cosine-similarity search over note embeddings, newest ties first."""
        try:
            qvec = embed(query)
        except Exception:  # noqa: BLE001 — embeddings unavailable → degrade to keyword search
            return self.search_notes_keyword(query, k)
        where, params = ["embedding is not null"], []
        if category:
            where.append("category = %s")
            params.append(category)
        if date_from:
            where.append("created_date >= %s")
            params.append(date_from)
        if date_to:
            where.append("created_date <= %s")
            params.append(date_to)
        clause = " and ".join(where)
        # <=> is cosine distance; score = 1 - distance so higher is more relevant.
        params = [qvec, *params, qvec, k]
        rows = self._many(
            f"""
            select id, title, content, category, tags, created_date, updated_date,
                   1 - (embedding <=> %s) as score
            from notes
            where {clause}
            order by embedding <=> %s
            limit %s;
            """,
            tuple(params),
        )
        return [
            NoteMatch(note=Note.model_validate({k2: v for k2, v in r.items() if k2 != "score"}),
                      score=float(r["score"]))
            for r in rows
        ]

    def search_notes_keyword(self, query: str, k: int = 5) -> list[NoteMatch]:
        """Simple case-insensitive keyword search (fallback / when embeddings off)."""
        rows = self._many(
            """
            select id, title, content, category, tags, created_date, updated_date
            from notes
            where title ilike %s or content ilike %s
            order by updated_date desc
            limit %s;
            """,
            (f"%{query}%", f"%{query}%", k),
        )
        return [NoteMatch(note=Note.model_validate(r), score=1.0) for r in rows]

    # ------------------------------------------------------- execution logs
    def save_execution_log(self, log: ExecutionLog) -> uuid.UUID:
        """Insert or update a run log (upsert by run_id)."""
        self._one(
            """
            insert into execution_logs
                (run_id, user_request, model, tools_called, tool_args, tool_results,
                 approval_status, errors, start_time, end_time, duration_ms, final_outcome)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (run_id) do update set
                model = excluded.model,
                tools_called = excluded.tools_called,
                tool_args = excluded.tool_args,
                tool_results = excluded.tool_results,
                approval_status = excluded.approval_status,
                errors = excluded.errors,
                end_time = excluded.end_time,
                duration_ms = excluded.duration_ms,
                final_outcome = excluded.final_outcome
            returning run_id;
            """,
            (
                str(log.run_id),
                log.user_request,
                log.model,
                Jsonb(log.tools_called),
                Jsonb(log.tool_args),
                Jsonb(log.tool_results),
                log.approval_status,
                Jsonb(log.errors),
                log.start_time,
                log.end_time,
                log.duration_ms,
                log.final_outcome,
            ),
        )
        return log.run_id

    def list_execution_logs(self, limit: int = 50) -> list[ExecutionLog]:
        rows = self._many(
            "select * from execution_logs order by start_time desc limit %s;", (limit,)
        )
        return [ExecutionLog.model_validate(r) for r in rows]

    # ----------------------------------------------------------- internals
    def _one(self, sql: str, params: tuple) -> dict:
        row = self._maybe_one(sql, params)
        if row is None:
            raise RepositoryError("Expected a row but got none.")
        return row

    def _maybe_one(self, sql: str, params: tuple) -> dict | None:
        with self._connect() as conn:
            return conn.execute(sql, params).fetchone()

    def _many(self, sql: str, params: tuple) -> list[dict]:
        with self._connect() as conn:
            return conn.execute(sql, params).fetchall()


# Convenience singleton for app code (tests construct their own with an injected dsn).
def get_repository() -> Repository:
    return Repository()
