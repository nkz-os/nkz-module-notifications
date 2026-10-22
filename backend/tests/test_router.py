"""Tests del router de Alert (inmediata vs digest)."""
from unittest.mock import MagicMock, patch

from app.dispatcher.router import EXTREME_ALERT_TYPES, _is_immediate, alert_to_info, handle_alert


def _alert(alert_type="rust_yellow", severity="high", status="active"):
    return {
        "id": f"urn:ngsi-ld:Alert:t:{alert_type}:p1",
        "type": "Alert",
        "alertType": {"type": "Property", "value": alert_type},
        "severity": {"type": "Property", "value": severity},
        "refEntity": {"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:p1"},
        "status": {"type": "Property", "value": status},
    }


def test_alert_to_info_normalizes():
    info = alert_to_info(_alert())
    assert info["alert_type"] == "rust_yellow"
    assert info["severity"] == "high"
    assert info["entity_id"] == "urn:ngsi-ld:AgriParcel:p1"


def test_alert_to_info_skips_non_active():
    assert alert_to_info(_alert(status="resolved")) is None


def test_is_immediate_extreme_high():
    assert _is_immediate({"alert_type": "frost", "severity": "high"}) is True
    assert _is_immediate({"alert_type": "weather_alert", "severity": "critical"}) is True


def test_is_not_immediate_low_or_non_extreme():
    assert _is_immediate({"alert_type": "frost", "severity": "medium"}) is False
    assert _is_immediate({"alert_type": "rust_yellow", "severity": "critical"}) is False


def test_handle_alert_queues_non_extreme(monkeypatch):
    queued = {}
    monkeypatch.setattr(
        "app.dispatcher.router._queue_for_digest",
        lambda tid, info, alert_name="", parcel_name="": queued.update(info) or True,
    )
    assert handle_alert("t", _alert()) == "queued"
    assert queued["alert_type"] == "rust_yellow"


def test_handle_alert_immediate_extreme(monkeypatch):
    disp = MagicMock()
    disp.has_delivered.return_value = False
    monkeypatch.setattr("app.dispatcher.NotificationDispatcher", lambda: disp)
    assert handle_alert("t", _alert(alert_type="frost", severity="critical")) == "immediate"
    disp.dispatch.assert_called_once()


def test_handle_alert_immediate_dedup(monkeypatch):
    disp = MagicMock()
    disp.has_delivered.return_value = True
    monkeypatch.setattr("app.dispatcher.NotificationDispatcher", lambda: disp)
    assert handle_alert("t", _alert(alert_type="frost", severity="critical")) == "skipped"
    disp.dispatch.assert_not_called()
