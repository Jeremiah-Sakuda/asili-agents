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

    # Routing posture. In production (Cloud Run) the deploy sets
    # GOOGLE_GENAI_USE_VERTEXAI=true, so every Gemini call goes through Vertex AI
    # under the service account — which is what the submission claims ("Gemini via
    # Vertex AI"). Surfacing it here makes the claim enforced in code, not just in
    # deploy YAML: when true, the runner routes via Vertex and does NOT also export
    # an API key (which google-genai would otherwise prefer, silently bypassing
    # Vertex). Local dev leaves this false and uses GOOGLE_API_KEY.
    google_genai_use_vertexai: bool = Field(
        default=False,
        description=(
            "Route all Gemini calls through Vertex AI. True in deployed/production "
            "(set via GOOGLE_GENAI_USE_VERTEXAI=true); false for local dev with an API key."
        ),
    )

    # Vertex AI — model tiering. Routine, high-volume turns (customer replies,
    # tool selection, pricing reasoning) run on the cheaper/faster tier; complex
    # composition + orchestration run on the larger tier. Routing most volume to
    # the cheap tier bends the cost-per-message curve down as a seller scales.
    gemini_model: str = Field(
        default="gemini-2.5-flash",
        description="Default Gemini model (the complex tier; also the baseline/control model).",
    )
    gemini_model_routine: str = Field(
        default="gemini-2.5-flash",
        description=(
            "Model for routine, high-volume turns (Messaging, Pricing agents). "
            "Defaults to the reliable gemini-2.5-flash for grounding/margin "
            "accuracy on the customer-facing path; set to gemini-2.5-flash-lite "
            "to opt into the cheaper high-volume tier once lite-tier grounding "
            "reliability is validated. The cost meter prices whichever model runs."
        ),
    )
    gemini_model_complex: str = Field(
        default="gemini-2.5-flash",
        description="Larger model for complex composition/orchestration (Operations Manager).",
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
        description=(
            "Command used to launch the MongoDB MCP server. 'npx' for local dev; "
            "in the container this is overridden to the absolute path of the baked, "
            "version-pinned binary so nothing is fetched from npm at runtime."
        ),
    )
    mcp_server_package: str = Field(
        default="mongodb-mcp-server@1.12.0",
        description=(
            "Exact, pinned npm spec for the MongoDB MCP server. Pinning the version "
            "(not @latest) prevents silently executing a newly-published — possibly "
            "compromised — release on a public endpoint that holds the Atlas string."
        ),
    )
    agent_run_timeout_s: float = Field(
        default=90.0,
        description=(
            "Hard ceiling (seconds) for a single agent/Gemini/MCP run. A run that "
            "exceeds this is cancelled and the endpoint returns 504, so one "
            "pathological request can't pin an instance for the full Cloud Run window."
        ),
    )

    # Telegram channel (customer DM transport)
    telegram_bot_token: str | None = Field(
        default=None,
        description="Telegram bot token from @BotFather. Enables the Telegram channel.",
    )
    telegram_webhook_secret: str | None = Field(
        default=None,
        description="Secret echoed by Telegram in the X-Telegram-Bot-Api-Secret-Token header.",
    )
    public_base_url: str | None = Field(
        default=None,
        description="Public base URL of this service, used to register the Telegram webhook.",
    )

    # ── Channel connectors: Instagram + WhatsApp (Meta) ──────────────────────
    # All per-seller OAuth/access tokens are encrypted at rest with
    # token_encryption_key and never logged. The web app holds none of these
    # server secrets; OAuth code-exchange happens here so the app secret stays
    # in one place.
    meta_app_id: str | None = Field(default=None, description="Meta App ID (Instagram Login).")
    meta_app_secret: str | None = Field(
        default=None, description="Meta App secret — verifies webhooks + exchanges OAuth codes."
    )
    instagram_redirect_uri: str | None = Field(
        default=None, description="OAuth redirect URI registered in the Meta App dashboard."
    )
    instagram_webhook_verify_token: str | None = Field(
        default=None, description="Token echoed back on the GET webhook verification handshake."
    )
    token_encryption_key: str | None = Field(
        default=None,
        description="Base64 32-byte AES-256-GCM key for encrypting per-seller channel tokens.",
    )
    oauth_state_secret: str | None = Field(
        default=None,
        description="HMAC secret used to sign the OAuth state that binds a flow to a seller_id.",
    )
    public_app_base_url: str | None = Field(
        default=None,
        description="Public base URL of the marketing/app site, for post-OAuth redirects back to onboarding.",
    )
    whatsapp_bsp_live: bool = Field(
        default=False,
        description="True once a WhatsApp BSP account + creds are wired; until then the connector is inert.",
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
