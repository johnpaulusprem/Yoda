"""Enterprise settings via pydantic-settings.

All configuration is loaded from environment variables (and optionally a
``.env`` file). See ``.env.example`` for the full list of supported variables.
"""
from __future__ import annotations
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide configuration loaded from environment variables.

    Grouped into sections: general, database, Redis, Azure identity,
    Entra ID auth, ACS, AI Foundry, bot behaviour, rate limiting, CORS,
    observability, embeddings, RAG, and DSPy.
    """
    APP_NAME: str = "YODA"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True
    BASE_URL: str = "http://localhost:8000"

    DATABASE_URL: str = ""
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10

    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_CACHE_DEFAULT_TTL: int = 300
    REDIS_CACHE_KEY_PREFIX: str = "yoda"
    REDIS_CACHE_BRIEF_TTL: int = 7200
    REDIS_CACHE_GRAPH_TTL: int = 300
    REDIS_CACHE_EMBEDDING_TTL: int = 86400
    REDIS_CACHE_LLM_TTL: int = 3600
    REDIS_CACHE_DASHBOARD_TTL: int = 120

    AZURE_TENANT_ID: str = ""
    AZURE_CLIENT_ID: str = ""
    AZURE_CLIENT_SECRET: str = ""

    # ─── Entra ID delegated auth (JWT validation for React frontend) ────
    AZURE_ISSUER: str = ""        # e.g. https://login.microsoftonline.com/{tenant}/v2.0
    AZURE_JWKS_URI: str = ""      # e.g. https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys
    AZURE_API_SCOPE: str = ""     # e.g. api://{client_id}/access_as_user

    ACS_CONNECTION_STRING: str = ""
    ACS_ENDPOINT: str = ""
    ACS_CALLBACK_BASE_URL: str = ""

    AI_FOUNDRY_ENDPOINT: str = ""
    AI_FOUNDRY_API_KEY: str = ""
    AI_FOUNDRY_DEPLOYMENT_NAME: str = "gpt-4o-mini"
    AI_FOUNDRY_DEPLOYMENT_NAME_COMPLEX: str = "gpt-4o"

    LONG_MEETING_THRESHOLD_MINUTES: int = 60
    BOT_JOIN_BEFORE_MINUTES: int = 1
    AUTO_JOIN_ENABLED: bool = True

    NUDGE_CHECK_INTERVAL_MINUTES: int = 60
    NUDGE_COOLDOWN_HOURS: int = 4
    NUDGE_ESCALATION_THRESHOLD: int = 3
    ESCALATION_DAYS: int = 3

    RATE_LIMIT_RPM: int = 100
    RATE_LIMIT_BURST: int = 20

    CORS_ALLOWED_ORIGINS: list[str] = []
    REQUIRE_AUTH: bool = True

    OTEL_EXPORTER_ENDPOINT: str = ""
    OTEL_SERVICE_NAME: str = "yoda"

    # ─── Server ─────────────────────────────────────────────────────
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # ─── Browser Bot (Playwright-based meeting bot) ─────────────────
    BROWSER_BOT_BASE_URL: str = ""
    BROWSER_BOT_API_KEY: str = ""
    INTER_SERVICE_HMAC_KEY: str = ""

    GRAPH_WEBHOOK_SECRET: str = ""
    ACS_CALLBACK_SECRET: str = ""

    # ─── Azure OpenAI Embeddings ──────────────────────────────────────
    AZURE_OPENAI_EMBEDDING_ENDPOINT: str = ""
    AZURE_OPENAI_EMBEDDING_KEY: str = ""
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = 1536

    # ─── RAG / Chunking ──────────────────────────────────────────────
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200

    # ─── DSPy ─────────────────────────────────────────────────────────
    DSPY_CACHE_ENABLED: bool = True
    DSPY_CACHE_TTL: int = 3600

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
