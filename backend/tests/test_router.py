"""Tests del router de Alert (inmediata vs digest)."""
from unittest.mock import MagicMock, patch

from app.dispatcher.router import EXTREME_ALERT_TYPES, _is_immediate, alert_to_info, handle_alert


def _alert(alert_type="rust_yellow", severity="high", status="active", description=None):
    e = {
        "id": f"urn:ngsi-ld:Alert:t:{alert_type}:p1",
        "type": "Alert",
        "alertType": {"type": "Property", "value": alert_type},
        "severity": {"type": "Property", "value": severity},
        "refEntity": {"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:p1"},
        "status": {"type": "Property", "value": status},
    }
    if description is not None:
        e["description"] = {"type": "Property", "value": description}
    return e


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


_DESC = "Nueva ruta planificada: sowing \u00b7 Parcel A"


def _route(severity, description=_DESC):
    e = _alert(alert_type="route_planned", severity=severity, description=description)
    e["refEntity"]["object"] = "urn:ngsi-ld:AgriParcelOperation:op1"
    return e


def test_route_planned_high_is_immediate_and_uses_description(monkeypatch):
    disp = MagicMock()
    disp.has_delivered.return_value = False
    monkeypatch.setattr("app.dispatcher.NotificationDispatcher", lambda: disp)
    assert handle_alert("tenant-a", _route("high")) == "immediate"
    args = disp.dispatch.call_args.args
    assert args[1] == "route_planned" and args[2] == "high"
    assert args[3]["summary"] == _DESC
    assert args[3]["title"] == "Route planned"


def test_route_planned_medium_goes_to_digest(monkeypatch):
    queued = {}
    monkeypatch.setattr(
        "app.dispatcher.router._queue_for_digest",
        lambda tid, info, alert_name="", parcel_name="": queued.update(info, name=alert_name) or True,
    )
    assert handle_alert("tenant-a", _route("medium")) == "queued"
    assert queued["name"] == _DESC


def test_route_planned_without_description_falls_back(monkeypatch):
    disp = MagicMock()
    disp.has_delivered.return_value = False
    monkeypatch.setattr("app.dispatcher.NotificationDispatcher", lambda: disp)
    handle_alert("acme", _route("high", description=None))
    assert disp.dispatch.call_args.args[3]["summary"].startswith("[HIGH] route_planned:")


def test_weather_alert_unchanged(monkeypatch):
    assert EXTREME_ALERT_TYPES == {
        "frost", "hail_proxy", "heat_stress", "wind_damage", "fire_30_30_30", "weather_alert"
    }
    disp = MagicMock()
    disp.has_delivered.return_value = False
    monkeypatch.setattr("app.dispatcher.NotificationDispatcher", lambda: disp)
    handle_alert("acme", _alert(alert_type="frost", severity="critical"))
    p = disp.dispatch.call_args.args[3]
    assert p["title"] == "Notification \u2014 frost"
    assert p["summary"] == "[CRITICAL] frost: urn:ngsi-ld:AgriParcel:p1"
