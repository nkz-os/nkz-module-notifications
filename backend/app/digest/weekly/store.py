"""Weekly report storage (notifications.* only; operational metadata, no telemetry, no emails)."""
import logging

from app.db import get_conn

logger = logging.getLogger(__name__)

_FINAL_STATUSES = {"sending", "sent", "failed", "skipped", "unknown"}


def _run(sql: str, params: tuple = (), fetch: str | None = None):
    conn = get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql, params)
            if fetch == "one":
                return cur.fetchone()
            if fetch == "rowcount":
                return cur.rowcount
            return None
    finally:
        conn.close()


def get_report(tenant_id: str) -> dict | None:
    row = _run(
        """
        SELECT tenant_id, iso_week, week_start, status, content, generated_at, delivered_at, updated_at
        FROM notifications.weekly_reports WHERE tenant_id = %s
        """,
        (tenant_id,),
        "one",
    )
    return dict(row) if row else None


def save_report(tenant_id: str, iso_week: str, week_start, status: str, content: dict) -> None:
    """Replace the tenant's single row. delivered_at is cleared when the week changes."""
    from psycopg2.extras import Json

    _run(
        """
        INSERT INTO notifications.weekly_reports
            (tenant_id, iso_week, week_start, status, content)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (tenant_id) DO UPDATE SET
            delivered_at = CASE WHEN notifications.weekly_reports.iso_week = EXCLUDED.iso_week
                                THEN notifications.weekly_reports.delivered_at ELSE NULL END,
            iso_week     = EXCLUDED.iso_week,
            week_start   = EXCLUDED.week_start,
            status       = EXCLUDED.status,
            content      = EXCLUDED.content,
            generated_at = now(),
            updated_at   = now()
        """,
        (tenant_id, iso_week, week_start, status, Json(content)),
    )


def mark_delivered(tenant_id: str, iso_week: str) -> None:
    _run(
        """
        UPDATE notifications.weekly_reports SET delivered_at = now(), updated_at = now()
        WHERE tenant_id = %s AND iso_week = %s
        """,
        (tenant_id, iso_week),
    )


def claim_delivery(tenant_id: str, iso_week: str, user_id: str, channel: str) -> bool:
    """Atomic: one winner per (tenant, week, user, channel). A failed row is reclaimed."""
    row = _run(
        """
        INSERT INTO notifications.weekly_report_deliveries
            (tenant_id, iso_week, user_id, channel, status, attempts)
        VALUES (%s, %s, %s, %s, 'sending', 1)
        ON CONFLICT (tenant_id, iso_week, user_id, channel) DO UPDATE SET
            status = 'sending',
            attempts = notifications.weekly_report_deliveries.attempts + 1,
            last_error = NULL,
            updated_at = now()
        WHERE notifications.weekly_report_deliveries.status = 'failed'
        RETURNING 1
        """,
        (tenant_id, iso_week, user_id, channel),
        "one",
    )
    return row is not None


def finish_delivery(
    tenant_id: str, iso_week: str, user_id: str, channel: str, status: str, error: str | None = None
) -> None:
    if status not in _FINAL_STATUSES:
        raise ValueError(f"invalid delivery status: {status}")
    _run(
        """
        UPDATE notifications.weekly_report_deliveries
        SET status = %s, last_error = %s, updated_at = now()
        WHERE tenant_id = %s AND iso_week = %s AND user_id = %s AND channel = %s
        """,
        (status, error, tenant_id, iso_week, user_id, channel),
    )


def expire_stale_sending(minutes: int = 15) -> int:
    n = _run(
        """
        UPDATE notifications.weekly_report_deliveries
        SET status = 'unknown', updated_at = now()
        WHERE status = 'sending' AND updated_at < now() - make_interval(mins => %s)
        """,
        (minutes,),
        "rowcount",
    )
    if n:
        logger.warning("weekly_report: %d stale sending deliveries set to unknown", n)
    return n


def purge_deliveries(days: int = 56) -> int:
    return _run(
        """
        DELETE FROM notifications.weekly_report_deliveries
        WHERE updated_at < now() - make_interval(days => %s)
        """,
        (days,),
        "rowcount",
    )


def is_opted_out(tenant_id: str, user_id: str, category: str = "weekly_report") -> bool:
    row = _run(
        """
        SELECT enabled FROM notifications.user_comm_prefs
        WHERE tenant_id = %s AND user_id = %s AND category = %s
        """,
        (tenant_id, user_id, category),
        "one",
    )
    return bool(row) and row["enabled"] is False


def set_pref(tenant_id: str, user_id: str, enabled: bool, category: str = "weekly_report") -> None:
    _run(
        """
        INSERT INTO notifications.user_comm_prefs (tenant_id, user_id, category, enabled)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (tenant_id, user_id, category) DO UPDATE
            SET enabled = EXCLUDED.enabled, updated_at = now()
        """,
        (tenant_id, user_id, category, enabled),
    )


def get_channels(tenant_id: str) -> dict:
    row = _run(
        "SELECT email, zulip FROM notifications.weekly_report_channels WHERE tenant_id = %s",
        (tenant_id,),
        "one",
    )
    if not row:
        return {"email": True, "zulip": False}
    return {"email": row["email"], "zulip": row["zulip"]}


def set_channels(tenant_id: str, email: bool, zulip: bool) -> None:
    _run(
        """
        INSERT INTO notifications.weekly_report_channels (tenant_id, email, zulip)
        VALUES (%s, %s, %s)
        ON CONFLICT (tenant_id) DO UPDATE
            SET email = EXCLUDED.email, zulip = EXCLUDED.zulip, updated_at = now()
        """,
        (tenant_id, email, zulip),
    )
