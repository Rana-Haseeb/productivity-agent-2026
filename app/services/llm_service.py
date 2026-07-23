"""
Provider-agnostic LLM service.

One class over any OpenAI-compatible endpoint. Switching from free OpenRouter models to
paid OpenAI is a **single change** — set ``LLM_PROVIDER=openai`` in ``.env`` (or pass
``provider="openai"`` here). Provider details live in ``config.PROVIDERS``; this module never
hard-codes a base URL or key.

Exposes what the tools and the LangGraph agent need:
- ``complete(system, user)``            → free-text answer.
- ``structured(system, user, schema)``  → a validated Pydantic object (native function-calling,
                                          with a JSON-prompt fallback for flaky free models).
- ``chat_model(tools=...)``             → a configured ``ChatOpenAI`` (optionally tool-bound) for
                                          the agent loop to drive directly.

Reliability (Week-2 gotchas, §9):
- **choices: null guard** — some free providers return an empty/null ``choices`` array; we detect
  the resulting empty content and raise a clean :class:`LLMError` instead of crashing.
- **retry + backoff** — transient 429/timeout errors are retried (``max_retries_per_tool``) with
  linear backoff, because the free tier is rate-limited (50 req/day).
- **user-safe errors** — every failure maps to a short message; keys and stack traces never leak.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.config import PROVIDERS, settings

T = TypeVar("T", bound=BaseModel)

# Substrings that indicate a transient, worth-retrying failure.
_TRANSIENT = ("429", "rate limit", "rate-limit", "timeout", "timed out", "temporarily",
              "overloaded", "502", "503", "504")


class LLMError(RuntimeError):
    """A user-safe LLM failure carrying a short, display-ready message."""


def _friendly(exc: Exception) -> LLMError:
    """Map any provider exception to a short, safe message (no keys, no stack traces)."""
    if isinstance(exc, LLMError):
        return exc
    msg = str(exc).lower()
    if "401" in msg or "invalid api key" in msg or "authentication" in msg:
        return LLMError("The AI provider rejected the API key. Check your credentials.")
    if "403" in msg or "permission" in msg:
        return LLMError("The AI provider denied access to this model (region/permission).")
    if "429" in msg or "rate" in msg or "quota" in msg:
        return LLMError("AI rate limit reached. Wait a moment, or switch model/provider.")
    if "timeout" in msg or "timed out" in msg:
        return LLMError("The AI request timed out. Please try again.")
    if "connection" in msg or "network" in msg or "getaddrinfo" in msg:
        return LLMError("Could not reach the AI provider. Check your connection.")
    if "not found" in msg or "404" in msg:
        return LLMError("That model id was not found at the provider. Try another model.")
    return LLMError("The AI service failed to produce a valid response.")


def _extract_json(text: str) -> str:
    """Pull the first balanced JSON object from a model response (tolerates code fences)."""
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
    """Thin, provider-aware wrapper over a LangChain ``ChatOpenAI`` client.

    Tries the primary model first; on a terminal failure (bad model id, empty ``choices``,
    exhausted retries) it automatically falls back to the next configured model. The model that
    actually answered is recorded in :attr:`last_used_model` for the execution log.
    """

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        fallback: bool = True,
    ):
        self.provider = provider or settings.provider
        if self.provider not in PROVIDERS:
            raise LLMError(f"Unknown provider {self.provider!r}. Options: {list(PROVIDERS)}.")
        self.cfg = PROVIDERS[self.provider]
        # Primary model: explicit arg > env override (default provider only) > provider default.
        if model:
            self.model = model
        elif self.provider == settings.provider:
            self.model = settings.active_model()
        else:
            self.model = self.cfg.default_model
        self.temperature = settings.temperature if temperature is None else temperature

        # Fallback chain: primary, then the provider's other models in order (deduped).
        self.models: list[str] = [self.model]
        if fallback:
            for m in self.cfg.models:
                if m not in self.models:
                    self.models.append(m)
        self.last_used_model: str | None = None

    # ---------------------------------------------------------------- describe
    def describe(self) -> str:
        """Short label for logs/UI, e.g. 'openrouter:cohere/north-mini-code:free (+2 fallback)'."""
        extra = f" (+{len(self.models) - 1} fallback)" if len(self.models) > 1 else ""
        return f"{self.provider}:{self.model}{extra}"

    # ------------------------------------------------------------------ client
    def _api_key(self) -> str:
        key = os.getenv(self.cfg.api_key_env)
        if not key:
            raise LLMError(
                f"Missing API key: set {self.cfg.api_key_env} in your environment / .env file."
            )
        return key

    def _client_for(self, model: str, temperature: float | None = None):
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            api_key=self._api_key(),
            base_url=self.cfg.base_url,
            temperature=self.temperature if temperature is None else temperature,
            max_tokens=settings.max_tokens,
            timeout=settings.tool_timeout_seconds,
            max_retries=0,  # we own retry/backoff so behaviour is explicit and testable
        )

    def chat_model(self, tools: list | None = None, temperature: float | None = None):
        """Return the PRIMARY chat model, optionally tool-bound (UI/simple use, no fallback)."""
        model = self._client_for(self.model, temperature)
        return model.bind_tools(tools) if tools else model

    # ------------------------------------------------------- retry & fallback
    def _run_with_retry(self, fn):
        """Retry a single-model call on transient errors; raise a user-safe LLMError otherwise."""
        attempts = settings.max_retries_per_tool + 1
        last: Exception | None = None
        for i in range(attempts):
            try:
                return fn()
            except LLMError:
                raise  # our own guard failures are already user-safe; don't retry
            except Exception as e:  # noqa: BLE001
                last = e
                transient = any(t in str(e).lower() for t in _TRANSIENT)
                if transient and i < attempts - 1:
                    time.sleep(1.5 * (i + 1))  # linear backoff
                    continue
                raise _friendly(e) from e
        raise _friendly(last or LLMError("unknown error"))

    def _try_models(self, per_model):
        """Run ``per_model(model_id)`` across the fallback chain until one succeeds."""
        last: LLMError | None = None
        for mdl in self.models:
            try:
                result = per_model(mdl)
                self.last_used_model = mdl
                return result
            except LLMError as e:
                last = e
                continue
        raise last or LLMError("All configured models failed.")

    # ------------------------------------------------------------------- calls
    def complete(self, system: str, user: str) -> str:
        return self._try_models(lambda m: self._complete_once(m, system, user))

    def _complete_once(self, model: str, system: str, user: str) -> str:
        def call() -> str:
            resp = self._client_for(model).invoke([("system", system), ("user", user)])
            content = getattr(resp, "content", None)
            if not content:  # §9 choices:null guard — empty/null choices → empty content
                raise LLMError("The AI returned an empty response (no choices).")
            return content if isinstance(content, str) else str(content)

        return self._run_with_retry(call)

    def structured(self, system: str, user: str, schema: type[T]) -> T:
        """Return a validated ``schema`` instance. Native structured output, JSON fallback, then next model."""
        return self._try_models(lambda m: self._structured_once(m, system, user, schema))

    def _structured_once(self, model: str, system: str, user: str, schema: type[T]) -> T:
        def native() -> T:
            client = self._client_for(model).with_structured_output(schema, method="function_calling")
            result = client.invoke([("system", system), ("user", user)])
            if result is None:
                raise LLMError("The AI returned no structured result.")
            if isinstance(result, schema):
                return result
            if isinstance(result, dict):
                return schema.model_validate(result)
            raise LLMError("The AI returned an unexpected structured type.")

        try:
            return self._run_with_retry(native)
        except LLMError:
            pass  # same model: fall back to explicit JSON prompting

        schema_json = json.dumps(schema.model_json_schema(), indent=2)
        json_system = (
            f"{system}\n\nReturn ONLY a JSON object that validates against this JSON Schema. "
            f"No prose, no code fences.\n\nJSON Schema:\n{schema_json}"
        )
        raw = self._complete_once(model, json_system, user)
        try:
            return schema.model_validate_json(_extract_json(raw))
        except (ValidationError, LLMError) as e:
            raise LLMError("The AI response did not match the required structure.") from e

    def invoke_tools(self, messages: list, tools: list):
        """Tool-calling invocation for the agent loop, with model fallback.

        ``messages`` is a LangChain message list; ``tools`` are tool schemas. Returns the model's
        ``AIMessage`` (which may contain ``tool_calls``). This is the single call the Phase-4
        LangGraph agent node uses so provider/fallback logic stays in one place.
        """
        def per_model(model: str):
            return self._run_with_retry(
                lambda: self._client_for(model).bind_tools(tools).invoke(messages)
            )

        return self._try_models(per_model)


# ---------------------------------------------------------------- convenience
def get_llm(provider: str | None = None, model: str | None = None) -> LLMService:
    """Factory used by app code. The '1-line provider swap' is just ``provider='openai'``."""
    return LLMService(provider=provider, model=model)


def available_models() -> dict[str, list[str]]:
    """Provider → model ids, for the UI model switcher (Phase 6)."""
    return {name: cfg.models for name, cfg in PROVIDERS.items()}
