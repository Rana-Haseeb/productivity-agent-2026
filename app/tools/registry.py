"""
Tool registry — the single source of truth for every tool the agent can call.

Each tool registers a :class:`ToolSpec` carrying its name, description, input/output
Pydantic models, and two safety flags: ``is_write`` and ``requires_approval``. The agent
reads these flags to decide when to pause for human approval (Requirement 7) and never
has to hard-code tool names.

``run_tool`` is the one execution path: it validates raw arguments against the input model
(turning bad/hallucinated args into a clean :class:`ToolValidationError`, Requirement 8),
then runs the tool with a :class:`ToolContext` (repository + optional LLM).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ValidationError


# --------------------------------------------------------------------- context
@dataclass
class ToolContext:
    """Dependencies passed to every tool. ``llm`` typed as ``Any`` to avoid an import cycle."""

    repo: Any                 # app.database.repository.Repository
    llm: Any = None           # app.services.llm_service.LLMService | None


# ---------------------------------------------------------------------- errors
class ToolError(RuntimeError):
    """A tool failed for a user-safe, reportable reason."""


class ToolValidationError(ToolError):
    """The provided arguments did not match the tool's input schema."""


# ------------------------------------------------------------------------ spec
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    func: Callable[[BaseModel, ToolContext], BaseModel]
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    is_write: bool = False
    requires_approval: bool = False


TOOL_REGISTRY: dict[str, ToolSpec] = {}


def register_tool(
    *,
    name: str,
    description: str,
    input_model: type[BaseModel],
    output_model: type[BaseModel],
    is_write: bool = False,
    requires_approval: bool = False,
) -> Callable:
    """Decorator that registers a tool function under ``name``."""

    def decorator(func: Callable) -> Callable:
        if name in TOOL_REGISTRY:
            raise ValueError(f"Duplicate tool name: {name}")
        TOOL_REGISTRY[name] = ToolSpec(
            name=name,
            description=description.strip(),
            func=func,
            input_model=input_model,
            output_model=output_model,
            is_write=is_write,
            requires_approval=requires_approval,
        )
        return func

    return decorator


# ----------------------------------------------------------------- accessors
def get_spec(name: str) -> ToolSpec:
    if name not in TOOL_REGISTRY:
        raise ToolError(f"Unknown tool: {name}")
    return TOOL_REGISTRY[name]


def all_specs() -> list[ToolSpec]:
    return list(TOOL_REGISTRY.values())


def requires_approval(name: str) -> bool:
    return get_spec(name).requires_approval


def run_tool(name: str, raw_args: dict, ctx: ToolContext) -> BaseModel:
    """Validate ``raw_args`` against the tool's schema, then execute it."""
    spec = get_spec(name)
    try:
        parsed = spec.input_model.model_validate(raw_args or {})
    except ValidationError as e:
        # Compact, user-safe summary of what was wrong.
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()
        )
        raise ToolValidationError(f"Invalid arguments for '{name}': {problems}") from e
    return spec.func(parsed, ctx)


def openai_tool_schemas() -> list[dict]:
    """OpenAI/OpenRouter ``tools=[...]`` schemas generated from the input models.

    Used in Phase 4 to bind tools to the model.
    """
    schemas = []
    for spec in all_specs():
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.input_model.model_json_schema(),
                },
            }
        )
    return schemas
