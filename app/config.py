"""Centralized runtime configuration.

All configuration is loaded from environment variables (optionally via a
``.env`` file). Nothing in this module ever prints or logs a secret value.
Modules should depend on :func:`get_settings` rather than reading
``os.environ`` directly, so that behaviour stays testable and overridable.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application settings sourced from the environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM provider selection (discovery-only; replay never touches this).
    llm_provider: str = Field(default="gemini", alias="LLM_PROVIDER")
    gemini_api_key: SecretStr | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-3.6-flash", alias="GEMINI_MODEL")

    # Demo application (target surface under automation).
    demo_app_host: str = Field(default="127.0.0.1", alias="DEMO_APP_HOST")
    demo_app_port: int = Field(default=8001, alias="DEMO_APP_PORT")
    demo_app_base_url: str = Field(
        default="http://127.0.0.1:8001", alias="DEMO_APP_BASE_URL"
    )

    # Main integration API.
    api_host: str = Field(default="127.0.0.1", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")

    # Runtime / evidence behaviour.
    evidence_dir: Path = Field(default=REPO_ROOT / "evidence", alias="EVIDENCE_DIR")
    capabilities_dir: Path = Field(
        default=REPO_ROOT / "capabilities", alias="CAPABILITIES_DIR"
    )
    headless_browser: bool = Field(default=True, alias="HEADLESS_BROWSER")
    agent_max_steps: int = Field(default=20, alias="AGENT_MAX_STEPS")
    replay_max_retries: int = Field(default=2, alias="REPLAY_MAX_RETRIES")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    def require_gemini_api_key(self) -> str:
        """Return the raw Gemini API key or raise a clear config error.

        Never logs the key. Called lazily, only when a Gemini call is about
        to be made, so the rest of the system (e.g. deterministic replay)
        works with no key configured at all.
        """

        if not self.gemini_api_key or not self.gemini_api_key.get_secret_value():
            raise RuntimeError(
                "GEMINI_API_KEY is not configured. Set it in your .env file "
                "(see .env.example) before running LLM-driven discovery. "
                "Deterministic replay does not require this."
            )
        return self.gemini_api_key.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    return Settings()
