"""Database persistence test — hits the real Supabase DB, skips if unreachable."""
from __future__ import annotations

import pytest

from app.database.models import Priority, TaskCreate
from app.database.repository import Repository


@pytest.fixture(scope="module")
def real_repo():
    try:
        repo = Repository()
        repo.ping()
    except Exception:  # noqa: BLE001
        pytest.skip("Database not reachable (set DATABASE_URL to the Supabase session pooler)")
    return repo


def test_task_persists_and_roundtrips(real_repo):
    created = real_repo.create_task(TaskCreate(title="pytest-persist-check", priority=Priority.LOW))
    try:
        fetched = real_repo.get_task(created.id)
        assert fetched.title == "pytest-persist-check"
        assert fetched.priority == Priority.LOW
    finally:
        assert real_repo.delete_task(created.id) is True  # clean up
