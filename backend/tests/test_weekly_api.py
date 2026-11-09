"""Weekly report HTTP routes: latest, channels, internal run."""
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app

P = "/api/notifications"
T = "tenant-a"
SECRET = {"X-Internal-Service-Secret": "dummy-secret"}


def hdr(role, tenant=T):
    return {"X-Tenant-ID": tenant, "X-User-ID": "u1", "X-User-Roles": role}


REPORT_CONTENT = {
    "status": "complete", "iso_week": "2026-W46", "week_start": "2026-11-09", "farm": "Acme",
    "missing": [], "alerts_failed": False, "extra_alerts": 0, "alerts": [], "changes": [],
    "figures": [], "unchanged": 0,
    "tasks": [{"id": "t1", "group": "now", "subject": {"type": "parcel", "id": "", "name": "North"},
               "kind": "irrigate", "when": {"type": "today", "date": None},
               "text": {"es": {"title": "Regar", "why": ""}}, "link": None, "relatedAlertId": None}],
}


def row(week="2026-W46", status="complete", content=None):
    return {"tenant_id": T, "iso_week": week, "week_start": date(2026, 11, 9), "status": status,
            "content": REPORT_CONTENT if content is None else content,
            "generated_at": datetime(2026, 11, 9, 6, tzinfo=timezone.utc), "delivered_at": None,
            "updated_at": datetime(2026, 11, 9, 6, tzinfo=timezone.utc)}


@pytest.fixture()
def client(monkeypatch):
    from app.api import weekly

    monkeypatch.setattr(weekly, "_now", lambda: datetime(2026, 11, 11, 10, tzinfo=timezone.utc))  # Wed W46
    state = {"row": row(), "channels": {"email": True, "zulip": False}}
    monkeypatch.setattr(weekly.store, "get_report", lambda t: state["row"])
    monkeypatch.setattr(weekly.store, "get_channels", lambda t: dict(state["channels"]))
    monkeypatch.setattr(weekly.store, "set_channels",
                        lambda t, e, z: state["channels"].update(email=e, zulip=z))
    with TestClient(app) as c:
        c.state = state
        yield c


# ---- latest ----

@pytest.mark.parametrize("role,code", [("Farmer", 403), ("TenantAdmin", 200), ("TechnicalConsultant", 200)])
def test_latest_requires_role(client, role, code):
    r = client.get(f"{P}/weekly-report/latest", headers=hdr(role))
    assert r.status_code == code
    if code == 403:
        assert "Regar" not in r.text


def test_latest_shape(client):
    r = client.get(f"{P}/weekly-report/latest?lang=es", headers=hdr("TenantAdmin")).json()
    assert r["reportId"] == "2026-W46" and r["weekStart"] == "2026-11-09" and r["status"] == "complete"
    assert r["generatedAt"].startswith("2026-11-09T06:00")
    assert "Regar" in r["plain"]["body"] and r["plain"]["title"]


def test_latest_lang_fallback(client):
    r = client.get(f"{P}/weekly-report/latest?lang=xx", headers=hdr("TenantAdmin"))
    assert r.status_code == 200


def test_latest_404_previous_week(client):
    client.state["row"] = row(week="2026-W45")
    assert client.get(f"{P}/weekly-report/latest", headers=hdr("TenantAdmin")).status_code == 404


def test_latest_404_no_report_and_no_sources_and_missed(client):
    client.state["row"] = None
    assert client.get(f"{P}/weekly-report/latest", headers=hdr("TenantAdmin")).status_code == 404
    client.state["row"] = row(status="no_sources", content={**REPORT_CONTENT, "status": "no_sources"})
    assert client.get(f"{P}/weekly-report/latest", headers=hdr("TenantAdmin")).status_code == 404
    client.state["row"] = row(status="missed", content={})
    assert client.get(f"{P}/weekly-report/latest", headers=hdr("TenantAdmin")).status_code == 404


def _no_orion(monkeypatch):
    from app.api import weekly

    class OrionCalled(BaseException):  # not swallowed by `except Exception`
        pass

    def boom(t):
        raise OrionCalled("latest must not call Orion")

    from app.digest.weekly import sources

    monkeypatch.setattr(sources, "parcel_timezones", boom)


def test_latest_never_calls_orion_and_absent_zone_is_utc(client, monkeypatch):
    _no_orion(monkeypatch)
    assert "time_zone" not in client.state["row"]["content"]
    assert client.get(f"{P}/weekly-report/latest", headers=hdr("TenantAdmin")).status_code == 200


def test_latest_uses_zone_stored_in_content(client, monkeypatch):
    from app.api import weekly

    _no_orion(monkeypatch)
    # Sunday 23:30 UTC is already Monday 2026-11-16 (W47) in a UTC+14 zone, still W46 in UTC
    monkeypatch.setattr(weekly, "_now", lambda: datetime(2026, 11, 15, 23, 30, tzinfo=timezone.utc))
    client.state["row"] = row(content={**REPORT_CONTENT, "time_zone": "Pacific/Kiritimati"})
    assert client.get(f"{P}/weekly-report/latest", headers=hdr("TenantAdmin")).status_code == 404
    client.state["row"] = row(content={**REPORT_CONTENT, "time_zone": "UTC"})
    assert client.get(f"{P}/weekly-report/latest", headers=hdr("TenantAdmin")).status_code == 200
    client.state["row"] = row(content={**REPORT_CONTENT, "time_zone": "Not/AZone"})  # invalid: UTC
    assert client.get(f"{P}/weekly-report/latest", headers=hdr("TenantAdmin")).status_code == 200


def test_latest_serves_missed_week_with_content(client, monkeypatch):
    _no_orion(monkeypatch)
    client.state["row"] = row(status="missed")
    r = client.get(f"{P}/weekly-report/latest", headers=hdr("TenantAdmin"))
    assert r.status_code == 200 and "Regar" in r.json()["plain"]["body"]


@pytest.mark.parametrize("content", [None, "text", [], {"status": "complete"},
                                     {**REPORT_CONTENT, "tasks": [{"id": "x"}]}])
def test_latest_malformed_content_is_404_not_500(client, content):
    client.state["row"] = row(content=content if content is not None else {})
    client.state["row"]["content"] = content
    assert client.get(f"{P}/weekly-report/latest", headers=hdr("TenantAdmin")).status_code == 404


# ---- channels ----

def test_channels_get_roles(client):
    assert client.get(f"{P}/weekly-report/channels", headers=hdr("TenantAdmin")).json() == {"email": True, "zulip": False}
    assert client.get(f"{P}/weekly-report/channels", headers=hdr("PlatformAdmin")).status_code == 200
    assert client.get(f"{P}/weekly-report/channels", headers=hdr("TechnicalConsultant")).status_code == 403


def test_channels_technical_consultant_forbidden(client):
    r = client.put(f"{P}/weekly-report/channels", json={"email": False, "zulip": True},
                   headers=hdr("TechnicalConsultant"))
    assert r.status_code == 403
    assert client.state["channels"] == {"email": True, "zulip": False}


def test_channels_put_admin(client):
    r = client.put(f"{P}/weekly-report/channels", json={"email": False, "zulip": True}, headers=hdr("TenantAdmin"))
    assert r.status_code == 200 and r.json() == {"email": False, "zulip": True}


def test_channels_put_rejects_non_bool(client):
    r = client.put(f"{P}/weekly-report/channels", json={"email": "yes", "zulip": True}, headers=hdr("TenantAdmin"))
    assert r.status_code == 422
    r = client.put(f"{P}/weekly-report/channels", json={"email": True}, headers=hdr("TenantAdmin"))
    assert r.status_code == 422


# ---- internal run ----

@pytest.fixture()
def run(client, monkeypatch):
    from app.api import weekly

    calls = {"dry": [], "manual": []}
    rep = {**REPORT_CONTENT}

    def fake_run_tenant(t, *, now, dry_run=False):
        calls["dry"].append((t, dry_run))
        return {"action": "DRY", "report": rep}

    def fake_manual(t, *, now, only_user_id, include_zulip=False):
        calls["manual"].append((t, only_user_id, include_zulip))
        return {"sent": True, "status": "complete", "iso_week": "2026-W46"}

    monkeypatch.setattr(weekly.schedule, "run_tenant", fake_run_tenant)
    monkeypatch.setattr(weekly.schedule, "run_manual", fake_manual)
    client.calls = calls
    return client


def test_run_requires_secret(run):
    assert run.post(f"{P}/internal/weekly-report/run", json={"tenant_id": T}).status_code == 401
    assert run.post(f"{P}/internal/weekly-report/run", json={"tenant_id": T},
                    headers={"X-Internal-Service-Secret": "wrong"}).status_code == 401
    # the user headers are not a credential
    assert run.post(f"{P}/internal/weekly-report/run", json={"tenant_id": T},
                    headers=hdr("PlatformAdmin")).status_code == 401


def test_run_fails_closed_on_empty_secret(run, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "internal_service_secret", "")
    assert run.post(f"{P}/internal/weekly-report/run", json={"tenant_id": T},
                    headers={"X-Internal-Service-Secret": ""}).status_code == 401


def test_run_works_with_master_secret_even_if_notify_refuses_master(run, monkeypatch):
    monkeypatch.setenv("NKZ_NOTIFY_ACCEPT_MASTER", "false")
    r = run.post(f"{P}/internal/weekly-report/run", json={"tenant_id": T}, headers=SECRET)
    assert r.status_code == 200


def test_dry_run_default_returns_report_and_email(run):
    r = run.post(f"{P}/internal/weekly-report/run", json={"tenant_id": T}, headers=SECRET)
    body = r.json()
    assert r.status_code == 200 and body["dry_run"] is True
    assert body["report"]["iso_week"] == "2026-W46"
    assert body["email"]["subject"] and body["email"]["content_html"] and body["email"]["text"]
    assert run.calls["dry"] == [(T, True)] and run.calls["manual"] == []


def test_real_run_requires_only_user_id(run):
    r = run.post(f"{P}/internal/weekly-report/run", json={"tenant_id": T, "dry_run": False}, headers=SECRET)
    assert r.status_code == 400
    assert run.calls["manual"] == []


def test_real_run_delivers_to_one_user(run):
    r = run.post(f"{P}/internal/weekly-report/run",
                 json={"tenant_id": T, "dry_run": False, "only_user_id": "u9", "zulip": True}, headers=SECRET)
    assert r.status_code == 200 and r.json()["sent"] is True
    assert run.calls["manual"] == [(T, "u9", True)]


def test_run_works_when_flag_disabled(run, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "weekly_report_enabled", False)
    assert run.post(f"{P}/internal/weekly-report/run", json={"tenant_id": T}, headers=SECRET).status_code == 200


def test_digest_task_still_starts(monkeypatch):
    import asyncio

    started = []

    async def fake(name):
        started.append(name)
        await asyncio.sleep(3600)

    from app import main as m
    import app.digest.sender as sender
    import app.digest.weekly.schedule as sch
    import app.services.subscriptions as subs

    monkeypatch.setattr(sender, "run_digest_sender", lambda *a, **k: fake("digest"))
    monkeypatch.setattr(subs, "run_subscription_reconciler", lambda *a, **k: fake("reconciler"))
    monkeypatch.setattr(sch, "run_weekly_scheduler", lambda *a, **k: fake("weekly"))
    with TestClient(m.create_app()):
        pass
    assert sorted(started) == ["digest", "reconciler", "weekly"]
