import os
from typing import Literal

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
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    # Auth settings (for initial superuser)
    FIRST_SUPERUSER: str = os.getenv("FIRST_SUPERUSER", "admin@example.com")
    FIRST_SUPERUSER_PASSWORD: str = os.getenv("FIRST_SUPERUSER_PASSWORD", "changethis")

    # Secret key for session management
    SECRET_KEY: str = os.getenv("SECRET_KEY", "changethis")

    # LiteLLM proxy — set LITELLM_PROXY_URL to route all LLM calls through the proxy for tracking.
    # Inside Docker: http://litellm:8080  |  Local dev (proxy running): http://localhost:8080
    # Leave empty to call upstream providers directly (no proxy).
    LITELLM_PROXY_URL: str = os.getenv("LITELLM_PROXY_URL", "")
    LITELLM_MASTER_KEY: str = os.getenv("LITELLM_MASTER_KEY", "")


settings = Settings()