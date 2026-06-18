"""Build the active channel-connector registry from settings.

A single instance per platform serves every seller (per-seller credentials are
passed at call time). The webhook + approve paths look connectors up by platform.
"""

from __future__ import annotations

from asili_agents.config import Settings
from asili_agents.integrations.channels.base import Channel
from asili_agents.integrations.channels.instagram import InstagramChannel
from asili_agents.integrations.channels.telegram import TelegramChannel
from asili_agents.integrations.channels.whatsapp import WhatsAppChannel


def build_channel_registry(settings: Settings) -> dict[str, Channel]:
    """Construct the platform -> connector map for this deployment."""
    return {
        "instagram": InstagramChannel(app_secret=settings.meta_app_secret),
        "whatsapp": WhatsAppChannel(
            app_secret=settings.meta_app_secret,
            live=settings.whatsapp_bsp_live,
        ),
        "telegram": TelegramChannel(webhook_secret=settings.telegram_webhook_secret),
    }
