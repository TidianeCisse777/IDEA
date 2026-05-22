import os

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_ignore_empty=True, extra="ignore"
    )

    # Database settings
    POSTGRES_SERVER: str = os.getenv("POSTGRES_SERVER", "localhost")
    POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "app")
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "admin")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "changethis")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        # Railway injects DATABASE_URL directly; local dev uses individual vars
        if url := os.getenv("DATABASE_URL"):
            return url.replace("postgres://", "postgresql://", 1)
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    # Auth settings (for initial superuser)
    FIRST_SUPERUSER: str = os.getenv("FIRST_SUPERUSER", "admin@example.com")
    FIRST_SUPERUSER_PASSWORD: str = os.getenv("FIRST_SUPERUSER_PASSWORD", "changethis")

    # Secret key for session management
    SECRET_KEY: str = os.getenv("SECRET_KEY", "changethis")

    # LLM settings — change LLM_MODEL + LLM_API_KEY in .env to swap providers
    # Examples:
    #   OpenAI   : LLM_MODEL=gpt-5.4-2026-03-05
    #   Anthropic: LLM_MODEL=claude-sonnet-4-6  LLM_API_KEY=$ANTHROPIC_API_KEY
    #   Jetstream: LLM_MODEL=openai/Llama-3.3-70B-Instruct  LLM_API_BASE=https://llm.jetstream-cloud.org/api
    LLM_MODEL: str = "gpt-5.4-2026-03-05"
    LLM_API_KEY: str | None = None
    LLM_API_BASE: str | None = None
    LLM_SUPPORTS_VISION: bool = True
    LLM_SUPPORTS_FUNCTIONS: bool = True
    LLM_TEMPERATURE: float = 0.2
    LLM_CONTEXT_WINDOW: int = 400000
    LLM_MAX_COMPLETION_TOKENS: int = 64000
    LLM_MAX_OUTPUT: int = 64000
    # Set to None for providers that don't support reasoning_effort (Anthropic, Jetstream2)
    LLM_REASONING_EFFORT: str | None = "low"

    # Session settings
    SESSION_IDLE_TIMEOUT: int = 3600
    SESSION_CLEANUP_INTERVAL: int = 1800


settings = Settings()