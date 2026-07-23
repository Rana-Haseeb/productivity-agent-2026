"""Tool definitions — importing this package registers all tools in ``TOOL_REGISTRY``.

Structure: task_tools · note_tools · planning_tools. Each tool has Pydantic in/out schemas
and read/write + approval flags. Use ``run_tool(name, args, ctx)`` to execute one safely.
"""
from __future__ import annotations

# Importing these modules runs the @register_tool decorators (side effect: populate registry).
from app.tools import note_tools, planning_tools, task_tools  # noqa: F401
from app.tools.registry import (  # noqa: F401
    TOOL_REGISTRY,
    ToolContext,
    ToolError,
    ToolSpec,
    ToolValidationError,
    all_specs,
    get_spec,
    openai_tool_schemas,
    register_tool,
    requires_approval,
    run_tool,
)

__all__ = [
    "TOOL_REGISTRY",
    "ToolContext",
    "ToolError",
    "ToolSpec",
    "ToolValidationError",
    "all_specs",
    "get_spec",
    "openai_tool_schemas",
    "register_tool",
    "requires_approval",
    "run_tool",
]
