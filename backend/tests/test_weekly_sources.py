"""Weekly report source gathering: every failure is a failed source, never empty data."""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
import requests

from app.digest.weekly import sources

T = "tenant-a"
REAL_FETCH_ALERTS = sources._fetch_alerts
REAL_FETCH_WEATHER = sources._fetch_weather_alerts
WEEK = date(2026, 11, 9)
URL = "http://mod-a-api-service:8000/api/mod-a/internal/weekly-report"
SRC = {"module_id": "mod-a", "display_name": "Module A", "weekly_report_url": URL}
GOOD = {"version": 1, "complete": True, "tasks": [], "changes": [], "figures": []}


def _resp(status=200, body=None, bad_json=False):
    r = MagicMock()
    r.status_code = status
    if bad_json:
        r.json.side_effect = ValueError("not json")
    else:
        r.json.return_value = GOOD if body is None else body
    return r


@pytest.fixture(autouse=True)
def base(monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "dummy-secret")
    from app.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setattr(sources, "list_sources", lambda t: [dict(SRC)])
    monkeypatch.setattr(sources, "_tenant_name", lambda t: "Acme")
    monkeypatch.setattr(sources, "_fetch_alerts", lambda t: ([], True))
    monkeypatch.setattr(sources, "_fetch_weather_alerts", lambda t, now=None: ([], True))


def _get(monkeypatch, **kw):
    m = MagicMock(**kw)
    monkeypatch.setattr(sources.requests, "get", m)
    return m


def test_ok_call_shape(monkeypatch):
    m = _get(monkeypatch, return_value=_resp())
    g = sources.gather(T, WEEK)
    assert g.sources[0].ok and g.sources[0].contribution is not None
    assert (g.sources[0].key, g.sources[0].label) == ("mod-a", "Module A")
    assert g.tenant_name == "Acme" and g.alerts_ok
    args, kw = m.call_args
    assert args[0] == URL
    assert kw["params"] == {"tenant_id": T, "week_start": "2026-11-09"}
    assert kw["headers"] == {"X-Internal-Service-Secret": "dummy-secret"}
    assert kw["timeout"] == 60
    assert kw["allow_redirects"] is False


def test_timeout_marks_failed(monkeypatch):
    _get(monkeypatch, side_effect=requests.Timeout())
    s = sources.gather(T, WEEK).sources[0]
    assert not s.ok and s.contribution is None


@pytest.mark.parametrize("status", [500, 502, 302, 404])
def test_non_200_marks_failed(monkeypatch, status):
    _get(monkeypatch, return_value=_resp(status))
    assert not sources.gather(T, WEEK).sources[0].ok


def test_invalid_json_marks_failed(monkeypatch):
    _get(monkeypatch, return_value=_resp(bad_json=True))
    assert not sources.gather(T, WEEK).sources[0].ok


def test_wrong_version_marks_failed(monkeypatch):
    _get(monkeypatch, return_value=_resp(body={**GOOD, "version": 2}))
    s = sources.gather(T, WEEK).sources[0]
    assert not s.ok and s.contribution is None


def test_complete_false_is_not_ok_but_keeps_data(monkeypatch):
    _get(monkeypatch, return_value=_resp(body={**GOOD, "complete": False}))
    s = sources.gather(T, WEEK).sources[0]
    assert not s.ok and s.contribution is not None


def test_one_failure_does_not_hide_others(monkeypatch):
    b = {"module_id": "mod-b", "display_name": "B", "weekly_report_url": "http://mod-b:80/x"}
    monkeypatch.setattr(sources, "list_sources", lambda t: [dict(SRC), b])
    _get(monkeypatch, side_effect=[requests.ConnectionError(), _resp()])
    out = sources.gather(T, WEEK).sources
    assert [s.ok for s in out] == [False, True]


def test_not_installed_not_called(monkeypatch):
    monkeypatch.setattr(sources, "list_sources", lambda t: [])
    m = _get(monkeypatch)
    assert sources.gather(T, WEEK).sources == []
    m.assert_not_called()


@pytest.mark.parametrize("url", [
    "https://crop-health.example.org/internal/weekly-report",
    "http://10.0.0.1:8000/x",
    "ftp://mod-a/x",
    "",
])
def test_url_must_be_in_cluster(monkeypatch, url):
    monkeypatch.setattr(sources, "list_sources", lambda t: [{**SRC, "weekly_report_url": url}])
    m = _get(monkeypatch)
    assert sources.gather(T, WEEK).sources == []
    m.assert_not_called()


def test_list_sources_raises_on_db_error(monkeypatch):
    monkeypatch.undo()
    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(sources, "get_conn", boom)
    with pytest.raises(RuntimeError):
        sources.list_sources(T)


def test_list_sources_filters_empty_urls(monkeypatch):
    monkeypatch.undo()
    cur = MagicMock()
    cur.fetchall.return_value = [
        {"module_id": "a", "display_name": "A", "weekly_report_url": "http://a:1/x"},
        {"module_id": "b", "display_name": "B", "weekly_report_url": " "},
        {"module_id": "c", "display_name": "C", "weekly_report_url": None},
    ]
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    monkeypatch.setattr(sources, "get_conn", lambda: conn)
    out = sources.list_sources(T)
    assert [s["module_id"] for s in out] == ["a"]
    sql, params = cur.execute.call_args[0]
    assert "module_report_sources" in sql and "module_installations" in sql and "is_enabled" in sql
    assert params == (T,)
    conn.close.assert_called_once()


# ---- Orion ----

class FakeOrion:
    """Pages of entities per type; records calls."""
    calls: list = []
    data: dict = {}
    fail: set = set()
    tenants: list = []

    def __init__(self, tenant_id, **kw):
        FakeOrion.tenants.append(tenant_id)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def query_entities(self, type=None, q=None, limit=100, offset=0, attrs=None, options=None):
        FakeOrion.calls.append({"type": type, "q": q, "limit": limit, "offset": offset})
        if type in FakeOrion.fail:
            raise RuntimeError("orion down")
        return FakeOrion.data.get(type, [])[offset:offset + limit]


@pytest.fixture()
def orion(monkeypatch):
    FakeOrion.calls, FakeOrion.data, FakeOrion.fail, FakeOrion.tenants = [], {}, set(), []
    monkeypatch.setattr(sources, "SyncOrionClient", FakeOrion)
    monkeypatch.setattr(sources, "_fetch_alerts", REAL_FETCH_ALERTS)
    monkeypatch.setattr(sources, "_fetch_weather_alerts", REAL_FETCH_WEATHER)
    return FakeOrion


def _alert(i, atype="irrigation_needed", severity="high", status="active", **extra):
    return {"id": f"urn:ngsi-ld:Alert:{i}", "type": "Alert", "alertType": atype,
            "severity": severity, "status": status, **extra}


def test_alerts_exclude_work_prefix(orion):
    orion.data["Alert"] = [_alert(1, "work_irrigate"), _alert(2), _alert(3, status="resolved")]
    alerts, ok = sources._fetch_alerts(T)
    assert ok and [a["id"] for a in alerts] == ["urn:ngsi-ld:Alert:2"]


def test_alerts_normalized_and_plain_kept(orion):
    plain = {"es": {"title": "t", "body": "b"}}
    orion.data["Alert"] = [{
        "id": "urn:ngsi-ld:Alert:9", "type": "Alert",
        "alertType": {"type": "Property", "value": "frost"},
        "severity": {"type": "Property", "value": "critical"},
        "status": {"type": "Property", "value": "active"},
        "plain": {"type": "Property", "value": plain},
    }]
    alerts, ok = sources._fetch_alerts(T)
    assert ok and alerts[0]["id"] == "urn:ngsi-ld:Alert:9"
    assert alerts[0]["plain"] == plain and alerts[0]["severity"] == "critical"


def test_alerts_without_plain_has_none(orion):
    orion.data["Alert"] = [_alert(1)]
    assert sources._fetch_alerts(T)[0][0]["plain"] is None


def test_alerts_paginates_with_explicit_limit(orion):
    orion.data["Alert"] = [_alert(i) for i in range(250)]
    alerts, ok = sources._fetch_alerts(T)
    assert ok and len(alerts) == 250
    assert all(isinstance(c["limit"], int) for c in orion.calls)
    assert [c["offset"] for c in orion.calls] == [0, 100, 200]


def test_alerts_failure(orion, monkeypatch):
    orion.fail = {"Alert"}
    alerts, ok = sources._fetch_alerts(T)
    assert not ok and alerts == []


def test_alerts_ok_false_if_weather_fails(orion):
    orion.fail = {"WeatherAlert"}
    g = sources.gather(T, WEEK)
    assert g.alerts_ok is False


def test_alerts_ok_false_if_alert_fails(orion):
    orion.fail = {"Alert"}
    assert sources.gather(T, WEEK).alerts_ok is False


NOW = datetime(2026, 11, 9, 7, 0, tzinfo=timezone.utc)


def _w(i, sev, valid_to=None, **extra):
    valid_to = valid_to or (NOW + timedelta(hours=5)).isoformat().replace("+00:00", "Z")
    return {"id": f"urn:ngsi-ld:WeatherAlert:{i}", "type": "WeatherAlert", "severity": sev,
            "description": f"d{i}", "validFrom": "2026-11-09T00:00:00Z", "validTo": valid_to, **extra}


def test_weather_alerts_severity_and_cap(orion):
    past = (NOW - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    orion.data["WeatherAlert"] = (
        [_w(i, "moderate") for i in range(4)]
        + [_w(10 + i, "severe") for i in range(3)]
        + [_w(20, "minor"), _w(21, "informational"), _w(22, "severe", valid_to=past)]
    )
    out, ok = sources._fetch_weather_alerts(T, now=NOW)
    assert ok and len(out) == 5
    assert [a["severity"] for a in out] == ["severe"] * 3 + ["moderate"] * 2
    assert {"id", "severity", "description", "validFrom", "validTo"} <= set(out[0])
    assert all(a["id"] not in ("urn:ngsi-ld:WeatherAlert:22",) for a in out)
    # alerts are geographic: read from the shared scope, validTo filtered server side
    assert orion.tenants[-1] == "shared"
    assert 'validTo>"2026-11-09T07:00:00Z"' == orion.calls[0]["q"]
    assert orion.calls[0]["type"] == "WeatherAlert" and isinstance(orion.calls[0]["limit"], int)


def test_weather_alerts_normalized(orion):
    orion.data["WeatherAlert"] = [{
        "id": "urn:ngsi-ld:WeatherAlert:1", "type": "WeatherAlert",
        "severity": {"type": "Property", "value": "severe"},
        "description": {"type": "Property", "value": "Wind"},
        "validFrom": {"type": "Property", "value": "2026-11-09T00:00:00Z"},
        "validTo": {"type": "Property", "value": "2026-11-09T20:00:00Z"},
    }]
    out, ok = sources._fetch_weather_alerts(T, now=NOW)
    assert ok and out[0]["description"] == "Wind" and out[0]["validTo"] == "2026-11-09T20:00:00Z"


def test_weather_alerts_failure(orion):
    orion.fail = {"WeatherAlert"}
    assert sources._fetch_weather_alerts(T, now=NOW) == ([], False)


# ---- parcel_timezones ----

def test_parcel_timezones(orion):
    orion.data["AgriParcel"] = [
        {"id": "p1", "timeZone": "Europe/Madrid"},
        {"id": "p2", "timeZone": {"type": "Property", "value": "UTC"}},
        {"id": "p3"},
    ]
    assert sources.parcel_timezones(T) == ["Europe/Madrid", "UTC"]
    assert orion.tenants[-1] == T


def test_parcel_timezones_raises_on_orion_failure(orion):
    orion.fail = {"AgriParcel"}
    with pytest.raises(RuntimeError):
        sources.parcel_timezones(T)
