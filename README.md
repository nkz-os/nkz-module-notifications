# nkz-module-notifications

Backend-only module: single delivery path for all platform alerts.

Subscribes to `Alert` entities in Orion (from any producer: risk, sensor-health,
greenhouse-dt, calibration) and delivers them via channels (email/push/Zulip/
Telegram). Extreme weather alerts go out immediately; the rest accumulate into a
grouped daily digest (max 2 emails/day per tenant).

## Endpoints

- `POST /api/notifications/internal/notify` — Orion subscription receiver (204 immediately, background processing).
- `GET /api/notifications/channels` — per-tenant channel config.
- `PUT /api/notifications/channels` — update per-tenant channel config.

## Config (env)

- `POSTGRES_URL` (required), `INTERNAL_SERVICE_SECRET` (required for subscriptions),
  `ORION_LD_URL`, `CONTEXT_URL`, `DIGEST_INTERVAL_HOURS` (default 12),
  `IMMEDIATE_MIN_SEVERITY` (default high).

## Schema

`notifications` schema: `tenant_alert_channels`, `alert_deliveries`, `digest_queue`.
