# Hail mary: Telegram channel (not planned for the demo)

Saved 2026-11-08 09:15 as a backup only. We decided not to ask judges to send messages from their own phones.

## Idea

A Telegram bot as a new channel on Lavanya's `MessagingService` (`backend/app/messaging.py`): forward a scam text, get the verdict back, CLICKED / YES / NO follow-ups as tap buttons, and a real trusted-contact alert to a teammate's phone. Long polling, so no webhook or tunnel; gated by `/start <TELEGRAM_DEMO_CODE>`; chat ids HMAC-hashed; fails closed.

## Setup

1. Telegram, @BotFather, `/newbot`, copy the token.
2. `.env`: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ENABLED=true`, `TELEGRAM_DEMO_CODE=hackutd`, `TELEGRAM_TRUSTED_CHAT_ID=`.

## Claude Code prompt

```
Wrap-up feature, about 60 minutes max: connect SentinelAI to a real messaging service with a Telegram bot. Read AGENTS.md, CHANGELOG.md, backend/app/messaging.py, backend/app/sms.py, backend/app/whatsapp.py and backend/app/trusted_contact.py first. Branch l16-telegram from main, with the usual claim and checkpoint steps.
Build it as a new channel on MessagingService; don't change the conversation logic, pipeline or agent.
1. backend/app/telegram.py: TelegramService(MessagingService). Long-poll getUpdates (25s) in a background thread started on app startup only when TELEGRAM_ENABLED=true and the token is set; stop cleanly on shutdown. httpx only, no new dependencies. sendMessage with Reply.buttons as an inline keyboard; callback_query maps to CLICKED, YES, NO, BLOCK, HELP and is always answered. Send "Checking…" and edit it as trail steps land; if editing fails, just send the verdict.
2. Access: only chats that sent "/start <TELEGRAM_DEMO_CODE>" get replies; others get one line saying it's a private demo. Chat ids in memory only; their HMAC (hash_phone) in logs, store and audit. Reuse RateLimiter. The /start reply says it's a hackathon demo, every chat is linked to the demo customer's sandbox bank, and Telegram can see what you send.
3. If TELEGRAM_TRUSTED_CHAT_ID is set, alert_trusted_contact sends trusted_contact.alert_note's content-free text to that chat. A "/trusted" command prints the sender's chat id.
4. Config flags in config.py and .env.example (TELEGRAM_ENABLED default false). Never log the token.
5. Tests with a fake Telegram API: start-code gate; forward then verdict with buttons; CLICKED gives "Was this you?" for the $900; YES/NO; trusted alert; fail closed; token never logged.
6. Live test with the real token, then docs (runbook section, DATA_SPEC note on what Telegram sees), CHANGELOG, PR with a merge commit.
Hard stop: if it isn't working end to end within 60 minutes, stop and leave main untouched.
```
