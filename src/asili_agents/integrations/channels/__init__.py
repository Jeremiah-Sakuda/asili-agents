"""Channel connector seam: one ``Channel`` interface, IG/WhatsApp/Telegram behind it."""

from asili_agents.integrations.channels.base import Channel, NormalizedInbound, SendOutcome
from asili_agents.integrations.channels.registry import build_channel_registry

__all__ = ["Channel", "NormalizedInbound", "SendOutcome", "build_channel_registry"]
