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

    # GCP Service Account (for Vertex AI authentication)
    google_application_credentials: str | None = Field(
        default=None,
        description="Path to GCP service account JSON file",
    )

    # Vertex AI
    vertex_search_datastore_id: str | None = Field(
        default=None,
        description="Vertex AI Search datastore ID for catalog grounding",
    )
    gemini_model: str = Field(
        default="gemini-2.5-flash",
        description="Gemini model to use for agents (Vertex AI serves the 2.5 series)",
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

    # MongoDB (system of record + MCP grounding)
    mongodb_uri: str | None = Field(
        default=None,
        description="MongoDB Atlas connection string (SRV URI). Required when use_mcp is True.",
    )
    mongodb_database: str = Field(
        default="asili",
        description="MongoDB database name",
    )
    use_mcp: bool = Field(
        default=False,
        description=(
            "Route the agents' catalog/stock reads through the MongoDB MCP server "
            "(npx mongodb-mcp-server). When False, agents use the in-process repository "
            "(used for local dev and tests)."
        ),
    )
    mcp_read_only: bool = Field(
        default=True,
        description="Run the MongoDB MCP server with --readOnly (agents never write via MCP).",
    )
    mcp_server_command: str = Field(
        default="npx",
        description="Command used to launch the MongoDB MCP server.",
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
