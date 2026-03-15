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
- `telegram-ingress` readiness is exposed via `GET /readyz`.
- Optional slash-command allowlist is supported via `TELEGRAM_ALLOWED_COMMANDS`.
- Minimal local command routing is implemented for `/help`, `/status`, and `/ask`.
- `X-Request-ID` continuity is preserved across ingress handling and downstream `agent-api` calls.
- Telegram-originated tool actions remain blocked inside `agent-api` policy enforcement.
- Operational alert delivery uses durable retry/dedupe semantics via a Postgres-backed outbox.

Что не реализовано сейчас:

- richer command/approval model beyond `/help`, `/status`, and `/ask`;
- broader incident-management beyond the current durable alert-delivery baseline; the MVP slice now emits one-shot escalation markers, events, and metrics for terminal failures and retry exhaustion, but does not add a separate secondary notification channel.

## Enterprise pattern (practical baseline)

Для enterprise-варианта лучше придерживаться:

- единый trusted ingress (`agent-api` через `telegram-ingress`) для пользовательского канала;
- отдельный Telegram бот/токен для алертинга, чтобы не смешивать пользовательские чаты и operational notifications;
- отдельный allowlist-командный слой (или metadata-канал) на уровне ingress или edge-сервисов;
- полный audit/корреляция по `request_id` для всех Telegram-запросов;
- строгий rotation policy для `TELEGRAM_BOT_TOKEN` и `TELEGRAM_WEBHOOK_SECRET_TOKEN`;
- отдельный `TELEGRAM_ALERT_AUTH_TOKEN` для `/telegram/alerts`, не оставленный пустым или placeholder, когда alert relay включен.

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
   - endpoint `GET /readyz` у `telegram-ingress` должен быть OK.
6. Проверить Telegram:
   - отправить тестовое сообщение боту;
   - убедиться, что пришел ответ.

7. Для алерт-бота настроить отдельные переменные:
   - `TELEGRAM_ALERT_BOT_TOKEN` — token отдельного Telegram-бота для алертов
   - `TELEGRAM_ALERT_AUTH_TOKEN` — статический секрет для входа в `/telegram/alerts`
   - `TELEGRAM_ALERT_CHAT_IDS` — список chat_id через запятую для доставки алертов
   - `TELEGRAM_ALERT_BOT_TOKEN` не должен совпадать с `TELEGRAM_BOT_TOKEN`
   - при включенном webhook `TELEGRAM_WEBHOOK_SECRET_TOKEN` не должен оставаться placeholder вроде `change-me`

Практический deploy contract:

- `infra/scripts/deploy.sh` fail-fast проверяет, что webhook mode не запускается с пустым или placeholder `TELEGRAM_WEBHOOK_SECRET_TOKEN`;
- тот же deploy path требует непустой `TELEGRAM_ALERT_AUTH_TOKEN`, когда alert relay реально включен;
- deploy path отдельно валидирует, что user bot и alert bot используют разные токены.

If webhook cannot be set publicly, set:

- `TELEGRAM_POLLING_ENABLED=true`
- `TELEGRAM_WEBHOOK_URL=` (empty/absent)

and run with long polling fallback.

## Command handling (what to decide in v1)

По умолчанию любая текстовая команда проходит как обычный user message.
When `TELEGRAM_ALLOWED_COMMANDS` is configured, commands outside that allowlist are dropped before the model path.

Рекомендуется внедрять минимальную прослойку:

- explicit routing for bot commands (например `/status`, `/help`, `/ask`, `/retry`),
- allowlist-проверка допустимых команд до `agent-api`,
- free-form texts are treated as normal chat requests.

Текущее поведение:

- slash-команда определяется как первое слово, начинающееся с `/`;
- если `TELEGRAM_ALLOWED_COMMANDS` заполнен, разрешённые команды проходят в `agent-api`;
- неизвестные команды возвращают `command_not_allowed`;
- free-form сообщения и разрешённые команды продолжают идти в модель.

## Alerting via Telegram

`telegram-ingress` в текущей реализации предоставляет endpoint для alert-ретрансляции:

- `POST /telegram/alerts` принимает JSON с `text` или `alerts` (формат близкий к Alertmanager webhook),
- нормализует событие в текст и маршрутизирует его через default/warning/critical recipient groups,
- использует `TELEGRAM_ALERT_BOT_TOKEN`, требует `X-Telegram-Alert-Token`, и fail-closed возвращает `503`, если relay частично сконфигурирован без `TELEGRAM_ALERT_AUTH_TOKEN`,
- поддерживает replay-safe dedupe только при наличии явного `X-Telegram-Alert-Idempotency-Key` от sender-а.

Policy baseline:

- `TELEGRAM_ALERT_CHAT_IDS` получает все принятые alert payloads и direct `text`/`message` payloads;
- `TELEGRAM_ALERT_WARNING_CHAT_IDS` получает `warning` и `critical`;
- `TELEGRAM_ALERT_CRITICAL_CHAT_IDS` получает только `critical`;
- `resolved` alerts по умолчанию фильтруются, если не включен `TELEGRAM_ALERT_SEND_RESOLVED=true`;
- overlap chat ids дедуплицируется на один message per request.

### Delivery semantics and failure boundaries

Текущая гарантия доставки для `POST /telegram/alerts`:

- delivery semantics для каждого target chat — `at-least-once`, не `exactly-once`;
- caller-supplied `X-Telegram-Alert-Idempotency-Key` дедуплицирует повторные submissions одного и того же upstream notification, но не дает глобальной exactly-once гарантии;
- outcome каждого target теперь пишется durably сразу после каждой send attempt, поэтому crash или transient storage failure после частично успешного fanout не должны переотправлять уже зафиксированный успешный префикс recipients;
- узкое окно дубля все еще остается между успешным `sendMessage` и durable записью outcome именно для текущего target;
- retryable Telegram/API/storage failures могут привести к повторной доставке одного и того же alert message в тот же chat;
- terminal Telegram errors (`400`, `401`, `403`, `404`) не ретраятся бесконечно и переводят target в failed path;
- `429 retry_after` и configured backoff учитываются при планировании следующей попытки.

Практический вывод для эксплуатации:

- downstream operations должны считать alert notifications idempotent-friendly и tolerate occasional duplicates;
- sender должен передавать стабильный idempotency key для одного upstream notification/retry chain;
- если duplicate alerts operationally неприемлемы, это требует отдельного exactly-once дизайна поверх текущего outbox baseline, а не только дополнительного retry tuning.

Текущие structured lifecycle events для расследования:

- `telegram_alert_delivery_claimed`:
  - `claim_origin=pending` для обычного due-claim;
  - `claim_origin=stale_reclaim` когда retry worker поднял delivery после истечения claim TTL.
- `telegram_alert_delivery_target_attempt_recorded`:
  - emitted только после durable записи outcome по target;
  - содержит `chat_id`, `attempt_status`, `error_code`, `retry_after_seconds`.
- `telegram_alert_delivery_finalized`:
  - содержит агрегатный итог `delivery_status` и counts по `sent_targets` / `pending_targets` / `failed_targets`.
- `telegram_alert_delivery_escalated`:
  - emitted один раз на delivery, когда в durable state записан escalation marker;
  - содержит `escalation_reason`, `escalated_at`, `delivery_status`, `failed_targets`.
- `telegram_alert_delivery_finalize_failed`:
  - показывает, что external sends могли уже произойти, но delivery-level finalize не зафиксировался.
- `telegram_alert_delivery_claim_skipped`:
  - полезен, когда due candidate уже был обработан другим worker или перестал быть due к моменту повторной попытки.

Быстрый operational triage:

- если есть `target_attempt_recorded` c `attempt_status=sent`, но затем `finalize_failed`, это crash/recovery-sensitive окно и возможный источник редкого duplicate на in-flight target;
- если растет доля `claim_origin=stale_reclaim`, нужно смотреть worker health, shutdown path и storage latency;
- если `attempt_status=pending` часто сопровождается `error_code=http_429`, проблема в Telegram backpressure, а не в storage path;
- если появился `telegram_alert_delivery_escalated`, смотреть durable marker в `telegram_alert_deliveries.escalated_at` / `escalation_reason`; `terminal_target_failure` означает permanent downstream rejection, `retry_exhausted` означает исчерпан bounded retry budget;
- если delivery зависает в `pending`, ключевой ориентир — `next_attempt_at` из `telegram_alert_delivery_finalized`.
- `finalize_failed` остается отдельным storage-sensitive сигналом и не записывает durable escalation marker, потому что finalize state сам не зафиксирован.

Prometheus-compatible export path:

- `GET /metrics` на `telegram-ingress` теперь экспортирует process-level counters для alert delivery;
- labels intentionally low-cardinality:
  - `telegram_alert_delivery_claim_total{origin="pending|stale_reclaim"}`
  - `telegram_alert_delivery_target_attempt_total{status="sent|pending|failed",error_class="none|http_429|http_4xx|http_5xx|other"}`
  - `telegram_alert_delivery_finalize_total{status="completed|pending|failed"}`
  - `telegram_alert_delivery_escalated_total{reason="terminal_target_failure|retry_exhausted|delivery_failed"}`
- без labels экспортируются:
  - `telegram_alert_delivery_claim_skipped_total`
  - `telegram_alert_delivery_target_attempt_persist_failed_total`
  - `telegram_alert_delivery_finalize_failed_total`

Практический смысл этих счётчиков:

- `claim_total{origin="stale_reclaim"}` показывает recovery pressure после истечения claim TTL;
- `target_attempt_total{status="pending",error_class="http_429"}` показывает Telegram backpressure;
- `target_attempt_persist_failed_total` сигнализирует, что side effect уже мог случиться, а durable outcome не записался;
- `finalize_failed_total` помогает отличать storage/finalize problems от send failures;
- `finalize_total{status="pending"}` удобно использовать как coarse retry-pressure indicator;
- `escalated_total{reason=...}` показывает, что delivery перешел в durable terminal/escalated state и уже требует operator attention, а не просто очередной retry.

Текущая эксплуатация:

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
  https://your-host/telegram/alerts \
  -H 'Content-Type: application/json' \
  -H "X-Telegram-Alert-Token: ${TELEGRAM_ALERT_AUTH_TOKEN}" \
  -H "X-Telegram-Alert-Idempotency-Key: ${UPSTREAM_NOTIFICATION_ID}" \
  -d '{"alerts":[{"status":"firing","labels":{"alertname":"telegram_ingress_down","service":"telegram-ingress","severity":"critical"},"annotations":{"summary":"ingress down","description":"telegram-ingress cannot accept updates"}}]}'
```

Для production-обвязки:

- route из Alertmanager/SLO monitor в webhook endpoint,
- прокидывать стабильный `X-Telegram-Alert-Idempotency-Key` для одного notification/retry chain;
- не строить этот key из rendered message text; одинаковый текст у разных notifications должен иметь разные keys;
- использовать route groups по severity (`default`, `warning`, `critical`),
- текущий ingress honors Telegram `429 retry_after` when scheduling durable alert retries и теперь пишет one-shot escalation marker для terminal failure / retry exhaustion; следующий follow-up slice, если понадобится, уже про broader incident-management, а не про базовый escalation contract.

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

- automated CI/local deterministic smoke:
  - `python infra/scripts/smoke-telegram-ingress.py`
  - expected environment: `telegram-ingress` + `agent-api` + fake model runtime + stubbed Telegram API
- canonical deploy integration:
  - `bash infra/scripts/smoke.sh` runs the Telegram smoke runner only when
    `TELEGRAM_SMOKE_*` inputs are configured for that environment
  - this is intended for deterministic smoke stacks, not for the default
    production rollout against the live Telegram network
  - without those deterministic inputs, production deploys rely on CI smoke plus
    the manual checks below
- `telegram-ingress` `GET /readyz` -> 200.
- отправить сообщение боту в пользовательском чате -> ответный message от бота.
- отправить второе сообщение в том же чате -> успешное продолжение того же backend conversation path.
- проверить, что невалидный webhook-secret отбрасывается.
- проверить, что невалидный `X-Telegram-Alert-Token` на `/telegram/alerts` отбрасывается.
- отправить `critical firing` alert payload -> доставка во все matching alert routes.
- отправить `resolved` alert payload -> default drop unless `TELEGRAM_ALERT_SEND_RESOLVED=true`.
- отправить короткий burst:
  - 1-й/2-й обработаны,
  - 3-й блокируется согласно лимитам.
- проверить, что bot update от самого бота игнорируется.

## Security reminders

- Не храните токены в репозитории.
- Не используйте Telegram API credentials в Open WebUI.
- Не добавляйте внешние secrets в prompt.
- Не обрабатывайте side-effect actions напрямую из raw текста без policy.
- Команда из Telegram (в т.ч. `/command`) должна быть валидирована локальной политикой до вызова `agent-api`; модель видит уже очищенный вход.
