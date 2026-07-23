"""
Execution logging — turns a finished agent run into a persisted 12-field record.

Requirement 10 fields: run_id, user_request, model, tools_called, tool_args, tool_results,
approval_status, errors, start_time, end_time, duration, final_outcome.

Privacy: only operational metadata is stored — never API keys, and never the model's
chain-of-thought (we log tool calls/results and outcomes, not hidden reasoning).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.database.models import ExecutionLog
from app.tools import get_spec


def _approval_status(state: dict[str, Any]) -> str:
    """Derive the run's approval status from what actually happened."""
    if state.get("final_outcome") == "rejected":
        return "rejected"
    if state.get("pending_approval"):
        return "pending"
    for entry in state.get("trace", []):
        if entry.get("ok"):
            try:
                if get_spec(entry["tool"]).is_write:
                    return "approved"  # a write executed → it was approved
            except Exception:  # noqa: BLE001
                continue
    return "none"


def _tool_result(entry: dict[str, Any]) -> dict[str, Any]:
    if "result" in entry:
        return entry["result"] if isinstance(entry["result"], dict) else {"value": entry["result"]}
    if entry.get("error"):
        return {"error": entry["error"]}
    if entry.get("note"):
        return {"note": entry["note"]}
    return {}


def build_execution_log(
    state: dict[str, Any],
    user_request: str,
    model: str | None,
    start_time: datetime,
    end_time: datetime | None = None,
) -> ExecutionLog:
    """Assemble (but do not persist) the ExecutionLog for a finished/paused run."""
    end = end_time or datetime.now()
    trace = state.get("trace", [])
    return ExecutionLog(
        run_id=state.get("run_id"),
        user_request=user_request,
        model=model,
        tools_called=[t["tool"] for t in trace],
        tool_args=[t.get("args", {}) for t in trace],
        tool_results=[_tool_result(t) for t in trace],
        approval_status=_approval_status(state),
        errors=[t["error"] for t in trace if t.get("error")],
        start_time=start_time,
        end_time=end,
        duration_ms=int((end - start_time).total_seconds() * 1000),
        final_outcome=state.get("final_outcome") or "completed",
    )


class RunLogger:
    """Persists execution logs via the repository. One instance per app session."""

    def __init__(self, repo):
        self.repo = repo

    def record(
        self,
        state: dict[str, Any],
        user_request: str,
        model: str | None,
        start_time: datetime,
        end_time: datetime | None = None,
    ) -> ExecutionLog:
        log = build_execution_log(state, user_request, model, start_time, end_time)
        self.repo.save_execution_log(log)
        return log

    def recent(self, limit: int = 50) -> list[ExecutionLog]:
        return self.repo.list_execution_logs(limit=limit)
