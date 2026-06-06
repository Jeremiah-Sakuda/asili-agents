"""Register this service's Telegram webhook with the Bot API.

Usage:
    TELEGRAM_BOT_TOKEN=... TELEGRAM_WEBHOOK_SECRET=... \
    PUBLIC_BASE_URL=https://<your-service>.run.app \
        python scripts/set_telegram_webhook.py

Points Telegram at  <PUBLIC_BASE_URL>/api/telegram/webhook  and (if a secret is
set) configures the secret token Telegram will echo in each webhook request.
"""

from __future__ import annotations

import asyncio

from asili_agents.config import get_settings
from asili_agents.integrations.telegram import TelegramClient


async def main() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set.")
    if not settings.public_base_url:
        raise SystemExit("PUBLIC_BASE_URL is not set (e.g. https://<service>.run.app).")

    url = settings.public_base_url.rstrip("/") + "/api/telegram/webhook"
    client = TelegramClient(settings.telegram_bot_token)
    response = await client.set_webhook(url, secret_token=settings.telegram_webhook_secret)
    print(f"setWebhook -> {url}")
    print(response)
    if not response.get("ok"):
        raise SystemExit("Telegram setWebhook failed (see response above).")


if __name__ == "__main__":
    asyncio.run(main())
