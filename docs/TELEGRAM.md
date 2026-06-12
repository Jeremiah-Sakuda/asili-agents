# Telegram Channel

> **Channel positioning (honest):** Telegram is the **demo / reference
> channel** — it proves the full live loop (inbound DM → grounded draft →
> approval gate → delivery) end-to-end with no platform-review gate. The
> channels the target sellers actually operate on are **Instagram and
> WhatsApp**: Instagram's API path is gated on Meta App Review (the founding
> cohort can run as test users in the meantime), and until then the **Tier-0
> paste-a-DM flow** in the console (`POST /api/conversations/paste`) covers any
> channel — the seller pastes the customer's message, approves the grounded
> draft, and sends it back inside the platform themselves, staying inside each
> channel's terms of service.

Asili can take customer messages over **Telegram** and answer them with the
same grounded, margin‑safe, **human‑approved** replies as the web console. This
document covers how it works, how to set it up, and the API surface.

> **The approval gate is preserved.** Unlike a typical bot that auto‑replies, an
> inbound Telegram message here becomes a **pending draft**. The seller approves
> (or edits/rejects) it, and only an *approved* draft is delivered back to the
> customer's chat. The agent never speaks to a customer unsupervised.

---

## Flow

```
Customer (Telegram)                 Asili service                         Seller
        │  message                         │                                │
        │ ───────────────▶ POST /api/telegram/webhook                       │
        │                                  │  verify secret token           │
        │                                  │  parse Update → InboundMessage │
        │                                  │  find/create conversation      │
        │   "typing…" ◀──── sendChatAction │                                │
        │                                  │  run the ADK team (grounded     │
        │                                  │  via MongoDB MCP), DRAFT only   │
        │                                  │  store as PENDING draft         │
        │                                  │                                │
        │                                  │   pending draft ──────────────▶ │ reviews in /app/
        │                                  │   POST /api/approve  ◀───────── │ approves / edits
        │   approved reply ◀──── sendMessage (Bot API)                       │
```

- **Inbound** → `POST /api/telegram/webhook` ([`api/main.py`](../src/asili_agents/api/main.py))
- **Outbound** → `TelegramClient.send_message` ([`integrations/telegram.py`](../src/asili_agents/integrations/telegram.py)), called from `POST /api/approve` only after approval
- The conversation id is `tg:<chat_id>`, so each Telegram chat maps to one conversation.

## Configuration

| Env var | Purpose |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather). Setting it enables the channel. |
| `TELEGRAM_WEBHOOK_SECRET` | Optional shared secret. Telegram echoes it in the `X-Telegram-Bot-Api-Secret-Token` header; the webhook rejects mismatches with `401`. |
| `PUBLIC_BASE_URL` | This service's public URL, used to register the webhook (e.g. `https://<service>.run.app`). |

When `TELEGRAM_BOT_TOKEN` is unset, the channel is simply off and the rest of the
service is unaffected.

## Setup

1. **Create a bot:** message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token.
2. **Set env** (locally in `.env`, or as Cloud Run env/secret):
   ```bash
   TELEGRAM_BOT_TOKEN=123456:ABC...
   TELEGRAM_WEBHOOK_SECRET=$(openssl rand -hex 16)
   PUBLIC_BASE_URL=https://<your-service>.run.app
   ```
3. **Deploy** the service so the webhook URL is reachable.
4. **Register the webhook:**
   ```bash
   python scripts/set_telegram_webhook.py
   # -> setWebhook https://<service>.run.app/api/telegram/webhook
   ```
5. **Test:** message your bot in Telegram. You'll see "typing…", a draft appears
   for approval in the seller inbox (`/app/`), and on approval the reply lands in
   the customer's chat.

## Endpoints

### `POST /api/telegram/webhook`
Receives Telegram `Update` objects.
- Verifies `X-Telegram-Bot-Api-Secret-Token` against `TELEGRAM_WEBHOOK_SECRET` (if set) → `401` on mismatch.
- Ignores non‑text updates (returns `{"ok": true, "skipped": true}`).
- Grounds a draft reply and stores it as **pending** (channel `telegram`, `chat_id`).
- Returns `{"ok": true, "conversation_id": "tg:<chat_id>", "pending": <bool>}`.

### `GET /api/inbox`
Lists conversations for the seller inbox — incoming Telegram chats (`tg:<chat_id>`)
and the demo conversation — each with `customer_name`, `channel`, `last_message`,
and `has_pending`. Conversations with a pending draft sort first. The web UI
(`/app/`) polls this so new customer messages surface live with a "pending" dot.

### `POST /api/approve` (existing)
When the approved draft's channel is `telegram`, the final text is delivered to
the customer's chat via `sendMessage` before the conversation is updated.

## Seller inbox (web UI)

The `/app/` console lists incoming Telegram conversations alongside the demo one.
The seller opens a conversation, sees the customer's message and the grounded
draft (with its source chips), and taps **Approve / Edit / Reject** — approval
delivers the reply to the customer's Telegram chat. No manual API call needed.

## `TelegramClient`

Thin async wrapper over the Bot API (`https://api.telegram.org/bot<TOKEN>/<method>`,
via `httpx`):

| Method | Bot API method | Use |
| --- | --- | --- |
| `send_message(chat_id, text, parse_mode="Markdown", reply_markup=None)` | `sendMessage` | Deliver an approved reply (Markdown supported). |
| `send_chat_action(chat_id, action="typing")` | `sendChatAction` | Show the customer a status while the team works. |
| `set_webhook(url, secret_token=None)` | `setWebhook` | Register the webhook (used by the script). |

## Security & notes

- The webhook secret keeps third parties from posting fake updates; always set it in production.
- Replies use Markdown `parse_mode`; keep drafts within Telegram's 4096‑char limit.
- Inbound conversations (`tg:<chat_id>`) and their pending drafts persist to
  MongoDB Atlas via `data/store.py` (`MongoStore`) when Atlas is connected — so a
  Telegram draft created on one Cloud Run instance can be approved on another and
  survives restarts; an in‑memory store is the local/test fallback.
- The agent run happens inline in the webhook (~15–20s with live MCP grounding),
  well within Telegram's webhook timeout; for very high volume, move it to a
  background task and return `200` immediately.
