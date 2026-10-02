"""Tests del digest sender (mensaje agrupado + marcado de enviados)."""
from unittest.mock import MagicMock, patch

from app.digest.sender import _build_message, send_digest_once


def test_build_message_groups():
    items = [
        {"alert_type": "rust_yellow", "alert_name": "Roya amarilla", "severity": "high", "parcel_name": "Finca Norte"},
        {"alert_type": "aphids", "alert_name": "Pulgón", "severity": "medium", "parcel_name": ""},
    ]
    msg = _build_message(items)
    assert "2 avisos activos" in msg
    assert "Roya amarilla — Finca Norte" in msg
    assert "[ALTO]" in msg and "[MEDIO]" in msg
    assert "Pulgón" in msg


def test_send_digest_once_sends_and_marks(monkeypatch):
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    # 1ª query: tenants con ítems; 2ª: ítems; 3ª: UPDATE sent
    cur.fetchall.side_effect = [
        [{"tenant_id": "test-tenant"}],
        [
            {"alert_type": "rust_yellow", "alert_name": "Roya", "severity": "high", "parcel_name": "F1"},
        ],
    ]
    monkeypatch.setattr("app.digest.sender.get_conn", lambda: conn)

    dispatcher = MagicMock()
    dispatcher.dispatch_digest.return_value = [{"channel": "email", "status": "sent"}]
    monkeypatch.setattr("app.dispatcher.NotificationDispatcher", lambda: dispatcher)

    result = send_digest_once()
    assert result == {"tenants": 1, "sent": 1}
    dispatcher.dispatch_digest.assert_called_once()
    # el UPDATE marca sent_at
    updates = [c.args[0] for c in cur.execute.call_args_list if "UPDATE" in str(c.args[0])]
    assert any("sent_at = now()" in u for u in updates)


def test_send_digest_once_skips_when_send_fails(monkeypatch):
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchall.side_effect = [
        [{"tenant_id": "test-tenant"}],
        [{"alert_type": "x", "alert_name": "", "severity": "low", "parcel_name": ""}],
    ]
    monkeypatch.setattr("app.digest.sender.get_conn", lambda: conn)

    dispatcher = MagicMock()
    dispatcher.dispatch_digest.return_value = [{"channel": "email", "status": "failed"}]
    monkeypatch.setattr("app.dispatcher.NotificationDispatcher", lambda: dispatcher)

    result = send_digest_once()
    assert result == {"tenants": 1, "sent": 0}
