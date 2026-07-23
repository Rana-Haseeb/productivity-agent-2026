"""
Environment-based configuration. No hard-coded secrets.

Everything sensitive is read from environment variables (loaded from a git-ignored
``.env`` in development). The agent is provider-agnostic: swapping from the free
OpenRouter models to paid OpenAI ``gpt-4o-mini`` for the graded eval run is a
single env-var change (``LLM_PROVIDER=openai``).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Project root = parent of the ``app`` package.
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


class ProviderConfig(BaseModel):
    """A single OpenAI-compatible LLM provider (OpenRouter, OpenAI, ...)."""

    label: str
    base_url: str
    api_key_env: str
    default_model: str
    models: list[str]


# Provider registry. All are OpenAI-compatible → driven through the same client.
# Free OpenRouter models below were verified to return valid tool_calls on 2026-07-23.
PROVIDERS: dict[str, ProviderConfig] = {
    "openrouter": ProviderConfig(
        label="OpenRouter (free)",
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        api_key_env="OPENROUTER_API_KEY",
        default_model="cohere/north-mini-code:free",
        models=[
            "cohere/north-mini-code:free",
            "nvidia/nemotron-3-nano-30b-a3b:free",
            "google/gemma-4-26b-a4b-it:free",
        ],
    ),
    "openai": ProviderConfig(
        label="OpenAI (paid — graded eval run)",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        default_model="gpt-4o-mini",
        models=["gpt-4o-mini", "gpt-4o"],
    ),
}


class Settings(BaseModel):
    """Typed, validated view over the environment."""

    # --- LLM ---
    provider: str = Field(default_factory=lambda: os.getenv("LLM_PROVIDER", "openrouter"))
    model_override: str | None = Field(default_factory=lambda: os.getenv("LLM_MODEL") or None)
    temperature: float = Field(default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0")))
    max_tokens: int = Field(default_factory=lambda: int(os.getenv("LLM_MAX_TOKENS", "1024")))

    # --- Execution limits (Requirement 9) — documented in README, see rationale below ---
    max_steps: int = 8            # hard cap on agent loop iterations → prevents runaway/looping
    max_retries_per_tool: int = 2  # transient tool failures retried, then surfaced
    tool_timeout_seconds: int = 30  # a single tool call may not exceed this

    # --- Data / embeddings ---
    database_url: str | None = Field(default_factory=lambda: os.getenv("DATABASE_URL"))
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384  # all-MiniLM-L6-v2 output dimension

    # ------------------------------------------------------------------ helpers
    def provider_config(self) -> ProviderConfig:
        if self.provider not in PROVIDERS:
            raise ValueError(
                f"Unknown LLM_PROVIDER={self.provider!r}. Choose one of {list(PROVIDERS)}."
            )
        return PROVIDERS[self.provider]

    def api_key(self) -> str | None:
        """Return the API key for the active provider, or None if unset."""
        return os.getenv(self.provider_config().api_key_env)

    def active_model(self) -> str:
        """Model to use: explicit override wins, else the provider default."""
        return self.model_override or self.provider_config().default_model

    def require_api_key(self) -> str:
        """Like ``api_key`` but raises a clear, user-safe error if missing (Requirement 8)."""
        key = self.api_key()
        if not key:
            env = self.provider_config().api_key_env
            raise RuntimeError(
                f"Missing API key: set {env} in your environment / .env file."
            )
        return key


# Import this singleton everywhere.
settings = Settings()
