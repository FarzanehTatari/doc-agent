"""Application configuration loaded from the environment or a `.env` file."""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = two levels up from this file (src/doc_agent/config.py → repo root).
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application settings.

    Values are read from (in order of precedence):
      1. Explicit constructor kwargs (used in tests)
      2. Environment variables
      3. `.env` file at the repo root
      4. The defaults below
    """

    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- API ---------------------------------------------------------
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_base_url: str = Field(
        default="https://api.anthropic.com", alias="ANTHROPIC_BASE_URL"
    )
    ai_model: str = Field(default="claude-opus-4-7", alias="AI_MODEL")

    # --- Logging -----------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO", alias="LOG_LEVEL"
    )

    @property
    def has_api_key(self) -> bool:
        """True iff a non-empty API key is present."""
        return bool(self.anthropic_api_key.strip())


# Module-level singleton — import this rather than instantiating Settings yourself.
settings = Settings()
