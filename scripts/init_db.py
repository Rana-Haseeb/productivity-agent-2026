"""
Database bootstrapper — run once after DATABASE_URL (session pooler) is set.

  python scripts/init_db.py            # ping -> migrate -> seed (if empty) -> verify
  python scripts/init_db.py --reseed   # also wipe + reseed sample data

Prints a clear report; safe to re-run (schema is idempotent).
"""
from __future__ import annotations

import sys
from datetime import date, timedelta

# Ensure project root importable when run as a script.
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.models import NoteCreate, Priority, TaskCreate, TaskFilter  # noqa: E402
from app.database.repository import Repository  # noqa: E402

TODAY = date.today()


def sample_tasks() -> list[TaskCreate]:
    return [
        TaskCreate(title="Finish website redesign", description="Homepage + pricing page revamp",
                   priority=Priority.HIGH, due_date=TODAY + timedelta(days=2),
                   tags=["web", "design"]),
        TaskCreate(title="Prepare Q3 marketing report", description="Pull campaign metrics",
                   priority=Priority.CRITICAL, due_date=TODAY + timedelta(days=3),
                   tags=["marketing", "report"]),
        TaskCreate(title="Fix login authentication bug", description="Users report 401 on SSO",
                   priority=Priority.CRITICAL, due_date=TODAY + timedelta(days=1),
                   tags=["backend", "bug"]),
        TaskCreate(title="Write unit tests for auth module", priority=Priority.MEDIUM,
                   due_date=TODAY + timedelta(days=5), tags=["testing"]),
        TaskCreate(title="Review open pull requests", priority=Priority.LOW,
                   tags=["review"]),
        TaskCreate(title="Plan sprint retrospective", description="Overdue — schedule it",
                   priority=Priority.MEDIUM, due_date=TODAY - timedelta(days=2),
                   tags=["planning"]),
    ]


def sample_notes() -> list[NoteCreate]:
    return [
        NoteCreate(
            title="Marketing campaign kickoff",
            content="Q3 campaign targets a 15% lift in signups. Channels: email, LinkedIn, "
            "partner webinars. Budget approved at $12k. Owner: Sara. Launch first week of August.",
            category="marketing", tags=["campaign", "q3"],
        ),
        NoteCreate(
            title="Project review meeting",
            content="Reviewed the productivity agent milestone. Decision: ship approval gate "
            "before public demo. Risk: free-model rate limits during eval. Action: budget OpenAI "
            "credit. Deadline for demo video: end of week.",
            category="meeting", tags=["review", "agent"],
        ),
        NoteCreate(
            title="Architecture decision — checkpointer",
            content="Chose LangGraph with an in-session-state checkpointer so Streamlit reruns "
            "cooperate with the approval interrupt. Postgres checkpointer deferred to future work.",
            category="engineering", tags=["architecture", "langgraph"],
        ),
    ]


def main() -> None:
    reseed = "--reseed" in sys.argv
    repo = Repository()

    print("1) Pinging database ...")
    repo.ping()
    print("   OK — reachable.")

    print("2) Applying schema (idempotent) ...")
    repo.init_schema()
    print("   OK — tables/enums/indexes ensured.")

    existing = repo.list_tasks(TaskFilter(limit=1))
    if existing and not reseed:
        print("3) Sample data already present — skipping seed (use --reseed to force).")
    else:
        print("3) Seeding sample data ...")
        for t in sample_tasks():
            repo.create_task(t)
        for n in sample_notes():
            repo.save_note(n)
        print(f"   OK — inserted {len(sample_tasks())} tasks + {len(sample_notes())} notes.")

    print("4) Verifying semantic note search ...")
    matches = repo.search_notes_semantic("what is the marketing budget for the campaign?", k=2)
    for m in matches:
        print(f"   [{m.score:.3f}] {m.note.title}")

    total = len(repo.list_tasks(TaskFilter(limit=1000)))
    print(f"\nDONE. Tasks in DB: {total}. Database layer is live. ✅")


if __name__ == "__main__":
    main()
