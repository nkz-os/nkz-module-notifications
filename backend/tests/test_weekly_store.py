"""Weekly report storage against a real PostgreSQL (atomicity cannot be mocked).

Skipped when POSTGRES_URL is unset or the conftest dummy.
"""
import os
from pathlib import Path

import pytest

POSTGRES_URL = os.getenv("WEEKLY_TEST_POSTGRES_URL") or os.getenv("POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL or "dummy" in POSTGRES_URL,
    reason="POSTGRES_URL not set or dummy (no DB in unit env)",
)

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"
T = "tenant-a"


@pytest.fixture()
def store(monkeypatch):
    import psycopg2

    from app.config import get_settings

    monkeypatch.setenv("POSTGRES_URL", POSTGRES_URL)
    get_settings.cache_clear()
    conn = psycopg2.connect(POSTGRES_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        for f in ("000_notifications_schema.sql", "002_weekly_report.sql"):
            cur.execute((MIGRATIONS / f).read_text())
        # idempotency: second run must not fail
        cur.execute((MIGRATIONS / "002_weekly_report.sql").read_text())
        for t in ("weekly_reports", "weekly_report_deliveries", "user_comm_prefs", "weekly_report_channels"):
            cur.execute(f"DELETE FROM notifications.{t}")
    conn.close()
    from app.digest.weekly import store as s

    yield s
    get_settings.cache_clear()


def _status(store, tenant, week, user, channel):
    conn = store.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, attempts FROM notifications.weekly_report_deliveries "
                "WHERE tenant_id=%s AND iso_week=%s AND user_id=%s AND channel=%s",
                (tenant, week, user, channel),
            )
            return cur.fetchone()
    finally:
        conn.close()


def test_claim_is_exclusive(store):
    assert store.claim_delivery(T, "2026-W45", "u1", "email") is True
    assert store.claim_delivery(T, "2026-W45", "u1", "email") is False


def test_failed_can_be_reclaimed(store):
    store.claim_delivery(T, "2026-W45", "u1", "email")
    store.finish_delivery(T, "2026-W45", "u1", "email", "failed", error="boom")
    assert store.claim_delivery(T, "2026-W45", "u1", "email") is True
    row = _status(store, T, "2026-W45", "u1", "email")
    assert row["status"] == "sending" and row["attempts"] == 2
    assert store.claim_delivery(T, "2026-W45", "u1", "email") is False


def test_failed_reclaim_has_one_winner(store):
    from concurrent.futures import ThreadPoolExecutor

    store.claim_delivery(T, "2026-W45", "u1", "email")
    store.finish_delivery(T, "2026-W45", "u1", "email", "failed")
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda _: store.claim_delivery(T, "2026-W45", "u1", "email"), range(8)))
    assert results.count(True) == 1


def test_unknown_cannot_be_reclaimed(store):
    store.claim_delivery(T, "2026-W45", "u1", "email")
    store.finish_delivery(T, "2026-W45", "u1", "email", "unknown")
    assert store.claim_delivery(T, "2026-W45", "u1", "email") is False


def test_sent_cannot_be_reclaimed(store):
    store.claim_delivery(T, "2026-W45", "u1", "email")
    store.finish_delivery(T, "2026-W45", "u1", "email", "sent")
    assert store.claim_delivery(T, "2026-W45", "u1", "email") is False


def test_skipped_cannot_be_reclaimed(store):
    store.claim_delivery(T, "2026-W45", "", "zulip")
    store.finish_delivery(T, "2026-W45", "", "zulip", "skipped")
    assert store.claim_delivery(T, "2026-W45", "", "zulip") is False


def test_finish_rejects_invalid_status(store):
    store.claim_delivery(T, "2026-W45", "u1", "email")
    with pytest.raises(ValueError):
        store.finish_delivery(T, "2026-W45", "u1", "email", "bogus")


def test_expire_stale_sending(store):
    store.claim_delivery(T, "2026-W45", "u1", "email")
    store.claim_delivery(T, "2026-W45", "u2", "email")
    conn = store.get_conn()
    with conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE notifications.weekly_report_deliveries SET updated_at = now() - interval '30 minutes' "
            "WHERE user_id='u1'"
        )
    conn.close()
    assert store.expire_stale_sending(15) == 1
    assert _status(store, T, "2026-W45", "u1", "email")["status"] == "unknown"
    assert _status(store, T, "2026-W45", "u2", "email")["status"] == "sending"


def test_purge_deliveries(store):
    store.claim_delivery(T, "2026-W40", "old", "email")
    store.claim_delivery(T, "2026-W45", "new", "email")
    conn = store.get_conn()
    with conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE notifications.weekly_report_deliveries SET updated_at = now() - interval '60 days' "
            "WHERE user_id='old'"
        )
    conn.close()
    assert store.purge_deliveries(56) == 1
    assert _status(store, T, "2026-W40", "old", "email") is None
    assert _status(store, T, "2026-W45", "new", "email") is not None


def test_default_not_opted_out(store):
    assert store.is_opted_out(T, "u1") is False


def test_opt_out_and_back(store):
    store.set_pref(T, "u1", False)
    assert store.is_opted_out(T, "u1") is True
    assert store.is_opted_out(T, "u2") is False
    store.set_pref(T, "u1", True)
    assert store.is_opted_out(T, "u1") is False


def test_save_replaces_previous_week(store):
    store.save_report(T, "2026-W45", "2026-11-02", "complete", {"a": 1})
    store.mark_delivered(T, "2026-W45")
    assert store.get_report(T)["delivered_at"] is not None
    store.save_report(T, "2026-W46", "2026-11-09", "partial", {"a": 2})
    conn = store.get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM notifications.weekly_reports WHERE tenant_id=%s", (T,))
        assert cur.fetchone()["n"] == 1
    conn.close()
    r = store.get_report(T)
    assert r["iso_week"] == "2026-W46" and r["content"] == {"a": 2} and r["status"] == "partial"
    assert r["delivered_at"] is None
    assert store.get_report("tenant-b") is None


def test_channels_default_and_set(store):
    assert store.get_channels(T) == {"email": True, "zulip": False}
    store.set_channels(T, False, True)
    assert store.get_channels(T) == {"email": False, "zulip": True}


def test_no_email_column(store):
    conn = store.get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema='notifications' AND column_name ILIKE '%%email%%' "
            "AND table_name IN ('weekly_reports','weekly_report_deliveries','user_comm_prefs','weekly_report_channels')"
        )
        rows = [(r["table_name"], r["column_name"]) for r in cur.fetchall()]
    conn.close()
    assert rows == [("weekly_report_channels", "email")]
