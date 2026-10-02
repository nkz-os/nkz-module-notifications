-- nkz-module-notifications/backend/migrations/000_notifications_schema.sql
-- Esquema del módulo de notificaciones: canales, entregas y cola de digest.
-- NO guarda telemetría (regla ZERO DIRECT DB WRITES).
CREATE SCHEMA IF NOT EXISTS notifications;

-- Config de canales por tenant (portada desde risk.tenant_alert_channels).
CREATE TABLE IF NOT EXISTS notifications.tenant_alert_channels (
    tenant_id  TEXT PRIMARY KEY,
    email      JSONB NOT NULL DEFAULT '{"enabled":false}'::jsonb,
    push       JSONB NOT NULL DEFAULT '{"enabled":false}'::jsonb,
    zulip      JSONB NOT NULL DEFAULT '{"enabled":false}'::jsonb,
    webhook    JSONB NOT NULL DEFAULT '{"enabled":false}'::jsonb,
    telegram   JSONB NOT NULL DEFAULT '{"enabled":false}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Registro transaccional de entrega por canal (dedup de reenvíos).
CREATE TABLE IF NOT EXISTS notifications.alert_deliveries (
    alert_id   TEXT NOT NULL,
    tenant_id  TEXT NOT NULL,
    severity   TEXT NOT NULL DEFAULT '',
    channel    TEXT NOT NULL,
    status     TEXT NOT NULL,             -- sent|failed|retry|skipped
    attempts   INT NOT NULL DEFAULT 1,
    last_error TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (alert_id, channel)
);

-- Cola de digest: avisos acumulados para el email agrupado diario.
-- Dedup: la misma Alert (id+severidad) entra una vez por día por tenant.
CREATE TABLE IF NOT EXISTS notifications.digest_queue (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    alert_id    TEXT NOT NULL,
    alert_type  TEXT NOT NULL,
    alert_name  TEXT NOT NULL DEFAULT '',
    severity    TEXT NOT NULL DEFAULT 'medium',
    parcel_name TEXT NOT NULL DEFAULT '',
    digest_date DATE NOT NULL DEFAULT CURRENT_DATE,
    queued_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at     TIMESTAMPTZ,
    UNIQUE (tenant_id, alert_id, severity, digest_date)
);
CREATE INDEX IF NOT EXISTS idx_digest_queue_unsent ON notifications.digest_queue(tenant_id) WHERE sent_at IS NULL;
