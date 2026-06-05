"""Configuration management for Asili Agents."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Google Cloud
    google_cloud_project: str = Field(
        default="asili-agents-hackathon",
        description="Google Cloud project ID",
    )
    google_cloud_location: str = Field(
        default="us-central1",
        description="Google Cloud region",
    )

    # Gemini API (for local development without Vertex AI)
    google_api_key: str | None = Field(
        default=None,
        description="Google Gemini API key (alternative to Vertex AI)",
    )

    # Vertex AI
    vertex_search_datastore_id: str | None = Field(
        default=None,
        description="Vertex AI Search datastore ID for catalog grounding",
    )
    gemini_model: str = Field(
        default="gemini-2.0-flash",
        description="Gemini model to use for agents",
    )

    # Telegram
    telegram_bot_token: str | None = Field(
        default=None,
        description="Telegram bot token for channel integration",
    )

    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///./asili_agents.db",
        description="Database connection URL",
    )

    # API
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8080)

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")

    # Demo mode
    demo_mode: bool = Field(
        default=True,
        description="Use mock data instead of live services",
    )

    # Pricing policy
    default_margin_floor: float = Field(
        default=0.45,
        description="Default minimum margin floor (45%)",
    )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
