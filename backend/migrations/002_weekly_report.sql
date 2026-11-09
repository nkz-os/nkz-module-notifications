-- Weekly farm report storage. Idempotent, expand-only. No email address is stored.
-- Apply as the database superuser (postgres): the module role nkz_module_notifications only has
-- USAGE on the schema, so it cannot create these tables. The ALTER ... OWNER TO statements at the
-- end hand them to the module role, which then reads and writes them without further grants.
CREATE SCHEMA IF NOT EXISTS notifications;

-- One row per tenant: the latest report only (no history).
CREATE TABLE IF NOT EXISTS notifications.weekly_reports (
    tenant_id    TEXT PRIMARY KEY,
    iso_week     TEXT NOT NULL,
    week_start   DATE NOT NULL,
    status       TEXT NOT NULL,
    content      JSONB NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at TIMESTAMPTZ,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Delivery ledger; user_id = '' for Zulip. Purged after 56 days.
CREATE TABLE IF NOT EXISTS notifications.weekly_report_deliveries (
    tenant_id  TEXT NOT NULL,
    iso_week   TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    channel    TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('sending','sent','failed','skipped','unknown')),
    attempts   INT NOT NULL DEFAULT 1,
    last_error TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, iso_week, user_id, channel)
);
CREATE INDEX IF NOT EXISTS idx_weekly_deliveries_updated
    ON notifications.weekly_report_deliveries(updated_at);

CREATE TABLE IF NOT EXISTS notifications.user_comm_prefs (
    tenant_id  TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    category   TEXT NOT NULL,
    enabled    BOOLEAN NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id, category)
);

CREATE TABLE IF NOT EXISTS notifications.weekly_report_channels (
    tenant_id  TEXT PRIMARY KEY,
    email      BOOLEAN NOT NULL DEFAULT true,
    zulip      BOOLEAN NOT NULL DEFAULT false,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Ownership: the module role owns its tables (skipped where the role does not exist, e.g. CI).
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nkz_module_notifications') THEN
    ALTER TABLE notifications.weekly_reports OWNER TO nkz_module_notifications;
    ALTER TABLE notifications.weekly_report_deliveries OWNER TO nkz_module_notifications;
    ALTER TABLE notifications.user_comm_prefs OWNER TO nkz_module_notifications;
    ALTER TABLE notifications.weekly_report_channels OWNER TO nkz_module_notifications;
  END IF;
END $$;
