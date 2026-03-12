# Runbook: Telegram Channel Operations

## Purpose

Define how Telegram is used as a production ingress channel, including two-way user communication and operational alerting.

This runbook separates:

- user-facing Telegram ingestion through `telegram-ingress`;
- operational alerting through a dedicated alert channel/bot.

## Current implemented scenarios

Из текущей реализации в репозитории:

- Telegram updates in webhook mode and long-polling fallback are supported.
- Only text-like payloads are processed (`text` or `caption`).
- Bot-origin messages are ignored.
- Basic abuse protections are enabled:
  - duplicate update suppression,
  - input length cap,
  - per-chat and global rate limiting,
  - webhook secret token verification.
- Every accepted user message is forwarded to `agent-api` and response is sent back to the same chat.
- `telegram-ingress` health is exposed via `GET /healthz`.

Что не реализовано сейчас:

- сложная командная модель (`/play`, `/status`, approval flow) до модели;
- отдельный поток для критических операционных алертов через Telegram;
- отдельные политики доставки по уровню важности/приоритетам для Telegram-команд.

## Enterprise pattern (practical baseline)

Для enterprise-варианта лучше придерживаться:

- единый trusted ingress (`agent-api` через `telegram-ingress`) для пользовательского канала;
- отдельный Telegram бот/токен для алертинга, чтобы не смешивать пользовательские чаты и operational notifications;
- отдельный allowlist-командный слой (или metadata-канал) на уровне ingress или edge-сервисов;
- полный audit/корреляция по `request_id` для всех Telegram-запросов;
- строгий rotation policy для `TELEGRAM_BOT_TOKEN` и `TELEGRAM_WEBHOOK_SECRET_TOKEN`.

## Two-way communication: user bot setup

`telegram-ingress` already provides both directions:

- inbound: Telegram update -> `telegram-ingress` -> `agent-api` -> response model.
- outbound: `telegram-ingress` sends reply text to `chat_id` via `sendMessage`.

Пошаговая настройка:

1. Создать Telegram-бота в BotFather и получить токен.
2. Скопировать `infra/env/telegram.example.env` в `infra/env/telegram.env`.
3. Заполнить в `infra/env/telegram.env`:
   - `TELEGRAM_BOT_TOKEN`
   - `AGENT_API_KEY`
   - `TELEGRAM_WEBHOOK_URL` (если доступен публичный HTTPS endpoint)
   - `TELEGRAM_WEBHOOK_PATH` (например `/telegram/webhook`)
   - `TELEGRAM_WEBHOOK_SECRET_TOKEN` (случайная строка; лучше с ротацией)
4. Убедиться, что `infra/caddy/Caddyfile` проксирует ` /telegram/webhook* ` на `telegram-ingress:8080`.
5. Поднять стек и проверить логи:
   - старт `telegram-ingress` должен зарегистрировать webhook;
   - endpoint `GET /healthz` у `telegram-ingress` должен быть OK.
6. Проверить Telegram:
   - отправить тестовое сообщение боту;
   - убедиться, что пришел ответ.

If webhook cannot be set publicly, set:

- `TELEGRAM_POLLING_ENABLED=true`
- `TELEGRAM_WEBHOOK_URL=` (empty/absent)

and run with long polling fallback.

## Command handling (what to decide in v1)

По умолчанию любая текстовая команда проходит как обычный user message.

Рекомендуется внедрять минимальную прослойку:

- explicit routing for bot commands (например `/status`, `/help`, `/ask`, `/retry`),
- whitelist проверку допустимых команд,
- all other free-form texts as normal chat requests,
- mapping command outcomes into model metadata (без добавления secrets в prompt).

Это должно контролироваться до вызова `agent-api`.

## Alerting via Telegram

Алертинг в текущей кодовой базе не реализован как часть `telegram-ingress`.

Рекомендуемая схема:

- использовать отдельный alert-bot (отдельный токен и, по возможности, отдельный Telegram account/channel),
- отправлять алерты только из наблюдаемости/мониторинга (not from user chat path),
- формировать сообщение с минимальным набором полей:
  - `env`,
  - `service`,
  - `severity`,
  - `request_id` или `correlation_id`,
  - короткий symptom + действие.

Базовая отправка сообщения для алерта:

```bash
curl -s -X POST \
  "https://api.telegram.org/bot${ALERTS_TELEGRAM_BOT_TOKEN}/sendMessage" \
  -H 'Content-Type: application/json' \
  -d '{"chat_id":"'${ALERT_CHAT_ID}'","text":"[ALERT] telegram-ingress degraded: ..."}'
```

Для production-обвязки:

- route из Alertmanager/SLO monitor в webhook endpoint,
- dedupe/retry в алерт-ретрансляторе,
- фильтрация по severity (`warning`, `critical`).

## Incident checks

### Если пользователь не получает ответ

1. Проверить `telegram-ingress` health.
2. Проверить, что webhook зарегистрирован корректно (`TELEGRAM_WEBHOOK_URL` + logs регистрации).
3. Проверить `agent-api` readiness.
4. Проверить `TELEGRAM_WEBHOOK_SECRET_TOKEN` и `TELEGRAM_BOT_TOKEN`.
5. Проверить rate-limit причины в логах (`rate_limited_*`).

### Если алерт не дошел

1. Проверить alert sender отдельным smoke-отправлением через `sendMessage`.
2. Проверить что alert bot и target chat доступны.
3. Проверить ротацию и валидность token.

## Smoke checks for Telegram channel

- `telegram-ingress` `GET /healthz` -> 200.
- отправить сообщение боту в пользовательском чате -> ответный message от бота.
- проверить, что невалидный webhook-secret отбрасывается.
- отправить короткий burst:
  - 1-й/2-й обработаны,
  - 3-й блокируется согласно лимитам.
- проверить, что bot update от самого бота игнорируется.

## Security reminders

- Не храните токены в репозитории.
- Не используйте Telegram API credentials в Open WebUI.
- Не добавляйте внешние secrets в prompt.
- Не обрабатывайте side-effect actions напрямую из raw текста без policy.

