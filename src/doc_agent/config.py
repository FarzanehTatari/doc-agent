"""Application configuration loaded from the environment or a `.env` file."""

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
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

    # --- Data paths (project_lib by default — gitignored) -----------
    data_dir: Path = Field(default=REPO_ROOT / "project_lib", alias="DATA_DIR")

    # --- Memory budgets ---------------------------------------------
    max_history: int = Field(default=12, alias="MAX_HISTORY", ge=1, le=200)
    max_token_budget: int = Field(default=40000, alias="MAX_TOKEN_BUDGET", ge=1000)
    response_token_budget: int = Field(
        default=8000, alias="RESPONSE_TOKEN_BUDGET", ge=256
    )
    facts_token_budget: int = Field(default=2000, alias="FACTS_TOKEN_BUDGET", ge=0)

    # --- RAG --------------------------------------------------------
    rag_enabled: bool = Field(default=True, alias="RAG_ENABLED")
    rag_chunk_size: int = Field(default=800, alias="RAG_CHUNK_SIZE", ge=100, le=8000)
    rag_chunk_overlap: int = Field(default=100, alias="RAG_CHUNK_OVERLAP", ge=0, le=2000)
    rag_top_k: int = Field(default=5, alias="RAG_TOP_K", ge=1, le=50)
    rag_token_budget: int = Field(default=4000, alias="RAG_TOKEN_BUDGET", ge=0)
    rag_min_score: float = Field(default=0.0, alias="RAG_MIN_SCORE", ge=0.0, le=1.0)
    rag_collection: str = Field(default="doc_agent_rag", alias="RAG_COLLECTION")

    # --- MATLAB bridge (Phase 2) -----------------------------------
    matlab_executable: str = Field(default="", alias="MATLAB_EXECUTABLE")
    matlab_timeout_s: int = Field(default=300, alias="MATLAB_TIMEOUT_S", ge=10, le=3600)

    @field_validator("data_dir", mode="before")
    @classmethod
    def _expand_data_dir(cls, v):
        """Expand ~ and resolve relative paths against the repo root."""
        if v is None or v == "":
            return REPO_ROOT / "project_lib"
        p = Path(v).expanduser()
        if not p.is_absolute():
            p = (REPO_ROOT / p).resolve()
        return p

    @property
    def has_api_key(self) -> bool:
        """True iff a non-empty API key is present."""
        return bool(self.anthropic_api_key.strip())

    @property
    def conversation_path(self) -> Path:
        return self.data_dir / "conversation.json"

    @property
    def facts_path(self) -> Path:
        return self.data_dir / "facts.md"

    @property
    def session_path(self) -> Path:
        return self.data_dir / "session.json"

    @property
    def rag_dir(self) -> Path:
        return self.data_dir / "rag"

    @property
    def extracted_dir(self) -> Path:
        return self.data_dir / "extracted"

    @property
    def matlab_scripts_dir(self) -> Path:
        return REPO_ROOT / "matlab"

    def ensure_data_dir(self) -> None:
        """Create the data directory if it doesn't exist yet."""
        self.data_dir.mkdir(parents=True, exist_ok=True)


# Module-level singleton — import this rather than instantiating Settings yourself.
settings = Settings()
