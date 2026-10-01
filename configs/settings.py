"""Central configuration for LocalAI Workspace.

All settings are environment-driven with safe local defaults.
Never hardcode secrets; read from environment / .env only.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Repository root (the directory containing ``backend/``, ``agents/``, ``configs/``…).
#: ``configs/settings.py`` → parents[0] = configs, parents[1] = repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]


def _first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


class Settings(BaseSettings):
    """Runtime settings. Values may be overridden with environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------------------------------------------------------------- app
    app_name: str = "LocalAI Workspace"
    app_version: str = "1.0.0"
    environment: str = Field(default_factory=lambda: os.environ.get("LAIW_ENV", "development"))
    debug: bool = False

    # ------------------------------------------------------------ storage
    repo_root: Path = REPO_ROOT
    data_dir: Path = Field(default_factory=lambda: Path(os.environ.get("LAIW_DATA_DIR", REPO_ROOT / "data")))
    storage_dir: Path = Field(default_factory=lambda: Path(os.environ.get("LAIW_STORAGE_DIR", REPO_ROOT / "storage")))

    # ----------------------------------------------------------- database
    # DATABASE_URL wins. Otherwise use SQLite local file (works with zero infra).
    database_url: str = Field(default_factory=lambda: os.environ.get("DATABASE_URL", ""))

    # ------------------------------------------------------------ workers
    redis_url: str = Field(default_factory=lambda: os.environ.get("REDIS_URL", ""))
    worker_mode: str = Field(default_factory=lambda: os.environ.get("LAIW_WORKER_MODE", "inline"))
    worker_concurrency: int = Field(default_factory=lambda: int(os.environ.get("LAIW_WORKER_CONCURRENCY", "4")))

    # --------------------------------------------------------------- auth
    jwt_secret: str = Field(default_factory=lambda: os.environ.get("LAIW_JWT_SECRET", ""))
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60 * 24 * 7
    allow_registration: bool = Field(default_factory=lambda: os.environ.get("LAIW_ALLOW_REGISTRATION", "true").lower() == "true")

    # --------------------------------------------------------------- LLM
    # Genspark sandbox exposes an OpenAI-compatible proxy through these vars.
    llm_base_url: str = Field(default_factory=lambda: _first_env("OPENAI_BASE_URL", "GSK_BASE_URL"))
    llm_api_key: str = Field(default_factory=lambda: _first_env("OPENAI_API_KEY", "GSK_API_KEY"))
    llm_anthropic_base_url: str = Field(default_factory=lambda: os.environ.get("ANTHROPIC_BASE_URL", ""))
    llm_anthropic_api_key: str = Field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    llm_default_model: str = Field(default_factory=lambda: os.environ.get("LAIW_DEFAULT_MODEL", "gpt-5.4-mini"))
    llm_fast_model: str = Field(default_factory=lambda: os.environ.get("LAIW_FAST_MODEL", "gpt-5.4-mini"))
    llm_timeout_seconds: float = Field(default_factory=lambda: float(os.environ.get("LAIW_LLM_TIMEOUT", "180")))
    llm_max_tokens: int = Field(default_factory=lambda: int(os.environ.get("LAIW_LLM_MAX_TOKENS", "4096")))

    # --------------------------------------------------- additional providers
    # Local models (Ollama / llama.cpp server / LM Studio all speak the
    # OpenAI-compatible surface; Ollama also exposes a native /api/tags list).
    ollama_base_url: str = Field(default_factory=lambda: os.environ.get("OLLAMA_BASE_URL", ""))
    ollama_api_key: str = Field(default_factory=lambda: os.environ.get("OLLAMA_API_KEY", ""))
    # Optional thinking control for Ollama. Unset ("") keeps the default
    # OpenAI-compatible path. "true"/"false" routes Ollama chat/stream through the
    # native /api/chat endpoint, which is the one that genuinely honours `think`
    # (the /v1 OpenAI-compatible surface ignores it).
    ollama_think: str = Field(default_factory=lambda: os.environ.get("LAIW_OLLAMA_THINK", ""))
    # Optional named OpenAI-compatible providers: LAIW_PROVIDER_<NAME>_URL / _KEY
    # e.g. LAIW_PROVIDER_GROQ_URL + LAIW_PROVIDER_GROQ_KEY
    # (parsed lazily by models.registry; never persisted or returned to clients)

    # ------------------------------------------------------- model discovery
    # Health/availability verdicts are cached for this many seconds so we never
    # hammer a provider. Discovery (model listing) uses its own shorter TTL.
    model_health_ttl_seconds: float = Field(default_factory=lambda: float(os.environ.get("LAIW_MODEL_HEALTH_TTL", "120")))
    model_probe_timeout_seconds: float = Field(default_factory=lambda: float(os.environ.get("LAIW_MODEL_PROBE_TIMEOUT", "20")))
    # A model is only marked AVAILABLE after a real minimal request succeeds.
    model_probe_enabled: bool = Field(default_factory=lambda: os.environ.get("LAIW_MODEL_PROBE_ENABLED", "true").lower() == "true")

    # -------------------------------------------------------------- tools
    http_timeout_seconds: float = 25.0
    max_upload_mb: int = Field(default_factory=lambda: int(os.environ.get("LAIW_MAX_UPLOAD_MB", "25")))
    rate_limit_per_minute: int = Field(default_factory=lambda: int(os.environ.get("LAIW_RATE_LIMIT", "240")))

    # ------------------------------------------------------------ runtime
    cors_origins: str = Field(default_factory=lambda: os.environ.get("LAIW_CORS_ORIGINS", "*"))
    log_level: str = Field(default_factory=lambda: os.environ.get("LAIW_LOG_LEVEL", "INFO"))

    # --------------------------------------------------------------- flags
    enable_code_execution: bool = Field(default_factory=lambda: os.environ.get("LAIW_ENABLE_CODE_EXECUTION", "true").lower() == "true")
    enable_network_tools: bool = Field(default_factory=lambda: os.environ.get("LAIW_ENABLE_NETWORK_TOOLS", "true").lower() == "true")
    image_provider_url: str = Field(default_factory=lambda: os.environ.get("LAIW_IMAGE_PROVIDER_URL", ""))
    image_provider_key: str = Field(default_factory=lambda: os.environ.get("LAIW_IMAGE_PROVIDER_KEY", ""))

    # ------------------------------------------------------------ derived
    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'localai.db'}"

    @property
    def is_sqlite(self) -> bool:
        return self.resolved_database_url.startswith("sqlite")

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def artifacts_dir(self) -> Path:
        return self.storage_dir / "artifacts"

    @property
    def uploads_dir(self) -> Path:
        return self.storage_dir / "uploads"

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.storage_dir, self.projects_dir, self.artifacts_dir, self.uploads_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    if not settings.jwt_secret:
        # Deterministic per-installation dev secret stored in data dir.
        secret_file = settings.data_dir / ".jwt_secret"
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        if secret_file.exists():
            settings.jwt_secret = secret_file.read_text(encoding="utf-8").strip()
        else:
            import secrets as _secrets

            settings.jwt_secret = _secrets.token_urlsafe(48)
            secret_file.write_text(settings.jwt_secret, encoding="utf-8")
            os.chmod(secret_file, 0o600)
    settings.ensure_dirs()
    return settings


settings = get_settings()
