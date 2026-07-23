"""
Provider-agnostic LLM service.

One class over any OpenAI-compatible endpoint (OpenRouter free models now, OpenAI paid
for the graded eval — a single env-var switch). Exposes two calls the tools/agent need:

- ``complete(system, user)``  → free-text answer.
- ``structured(system, user, schema)`` → a validated Pydantic object.

``structured`` first tries native function-calling structured output; if a flaky free model
doesn't cooperate, it falls back to a JSON-prompt + parse. Errors are mapped to short,
user-safe messages (never leak keys or stack traces — Requirement 8).
"""
from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.config import PROVIDERS, settings

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """User-safe LLM failure with a short message."""


def _friendly(exc: Exception) -> LLMError:
    msg = str(exc).lower()
    if "401" in msg or "auth" in msg or "invalid api key" in msg:
        return LLMError("The AI provider rejected the API key. Check your credentials.")
    if "403" in msg or "permission" in msg:
        return LLMError("The AI provider denied access to this model (region/permission).")
    if "429" in msg or "rate" in msg or "quota" in msg:
        return LLMError("AI rate limit reached. Wait a moment or switch provider/model.")
    if "timeout" in msg or "timed out" in msg:
        return LLMError("The AI request timed out. Please try again.")
    if "connection" in msg or "network" in msg:
        return LLMError("Could not reach the AI provider. Check your connection.")
    return LLMError("The AI service failed to produce a valid response.")


def _extract_json(text: str) -> str:
    """Pull the first balanced JSON object out of a model response (strip code fences)."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    start = text.find("{")
    if start == -1:
        raise LLMError("Model did not return JSON.")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise LLMError("Model returned truncated JSON.")


class LLMService:
    """Thin wrapper over a LangChain ``ChatOpenAI`` client."""

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
    ):
        self.provider = provider or settings.provider
        if self.provider not in PROVIDERS:
            raise LLMError(f"Unknown provider {self.provider!r}.")
        self.cfg = PROVIDERS[self.provider]
        self.model = model or settings.active_model()
        self.temperature = settings.temperature if temperature is None else temperature

    def _client(self):
        from langchain_openai import ChatOpenAI

        api_key = settings.api_key() if self.provider == settings.provider else None
        # Fall back to the provider's own env var when running a non-default provider.
        api_key = api_key or __import__("os").getenv(self.cfg.api_key_env)
        if not api_key:
            raise LLMError(f"Missing API key ({self.cfg.api_key_env}).")
        return ChatOpenAI(
            model=self.model,
            api_key=api_key,
            base_url=self.cfg.base_url,
            temperature=self.temperature,
            max_tokens=settings.max_tokens,
            timeout=settings.tool_timeout_seconds,
            max_retries=1,
        )

    # ------------------------------------------------------------------ calls
    def complete(self, system: str, user: str) -> str:
        try:
            resp = self._client().invoke([("system", system), ("user", user)])
        except Exception as e:  # noqa: BLE001
            raise _friendly(e) from e
        content = getattr(resp, "content", None)
        if not content:
            raise LLMError("The AI returned an empty response.")
        return content if isinstance(content, str) else str(content)

    def structured(self, system: str, user: str, schema: type[T]) -> T:
        """Return a validated ``schema`` instance from the model."""
        # 1) native structured output (function calling)
        try:
            client = self._client().with_structured_output(schema, method="function_calling")
            result = client.invoke([("system", system), ("user", user)])
            if isinstance(result, schema):
                return result
            if isinstance(result, dict):
                return schema.model_validate(result)
        except Exception:  # noqa: BLE001 — fall through to JSON fallback
            pass

        # 2) fallback: ask for JSON matching the schema, then parse
        schema_json = json.dumps(schema.model_json_schema(), indent=2)
        json_system = (
            f"{system}\n\nReturn ONLY a JSON object that validates against this JSON Schema. "
            f"No prose, no code fences.\n\nJSON Schema:\n{schema_json}"
        )
        raw = self.complete(json_system, user)
        try:
            return schema.model_validate_json(_extract_json(raw))
        except (ValidationError, LLMError) as e:
            raise LLMError("The AI response did not match the required structure.") from e
