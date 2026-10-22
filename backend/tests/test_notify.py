"""Tests del receptor /internal/notify (204 inmediato, background)."""
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.middleware import verify_internal_secret


def test_notify_invalid_payload():
    app.dependency_overrides[verify_internal_secret] = lambda: None
    try:
        with TestClient(app) as c:
            r = c.post("/api/notifications/internal/notify", json={"data": "not-a-list"})
            assert r.status_code == 400
    finally:
        app.dependency_overrides.pop(verify_internal_secret, None)


def test_notify_returns_204_without_processing_sync():
    app.dependency_overrides[verify_internal_secret] = lambda: None
    with patch("app.api.internal._process_alert_background") as bg_mock:
        try:
            with TestClient(app) as c:
                r = c.post(
                    "/api/notifications/internal/notify",
                    json={"data": [{"id": "urn:ngsi-ld:Alert:x", "type": "Alert"}]},
                    headers={"NGSILD-Tenant": "test-tenant"},
                )
                assert r.status_code == 204
        finally:
            app.dependency_overrides.pop(verify_internal_secret, None)


def test_notify_ignores_non_alert_entities():
    app.dependency_overrides[verify_internal_secret] = lambda: None
    with patch("app.api.internal._parcel_names", return_value={}), patch(
        "app.api.internal._process_alert_background"
    ) as bg_mock:
        try:
            with TestClient(app) as c:
                r = c.post(
                    "/api/notifications/internal/notify",
                    json={"data": [{"id": "urn:ngsi-ld:AgriParcel:p1", "type": "AgriParcel"}]},
                    headers={"NGSILD-Tenant": "test-tenant"},
                )
                assert r.status_code == 204
        finally:
            app.dependency_overrides.pop(verify_internal_secret, None)


def test_notify_auth_accepts_derived_token_and_master_until_contracted(monkeypatch):
    """The token bound to this tenant and host passes; the master passes only while
    accepted; a token of another tenant never does."""
    from nkz_platform_sdk.notify_auth import TOKEN_HEADER, notification_token

    url = "/api/notifications/internal/notify"
    body = {"data": []}
    # Starlette's TestClient sends Host: testserver; the token binds to that host.
    token = notification_token("dummy-secret", "tenant-a", "testserver")
    monkeypatch.setenv("NKZ_NOTIFY_ACCEPT_MASTER", "false")
    with TestClient(app) as c:
        ok = c.post(url, json=body, headers={"NGSILD-Tenant": "tenant-a", TOKEN_HEADER: token})
        assert ok.status_code == 204
        other = c.post(url, json=body, headers={"NGSILD-Tenant": "tenant-b", TOKEN_HEADER: token})
        assert other.status_code == 401
        master = c.post(url, json=body, headers={
            "NGSILD-Tenant": "tenant-a", "X-Internal-Service-Secret": "dummy-secret"})
        assert master.status_code == 401
        monkeypatch.setenv("NKZ_NOTIFY_ACCEPT_MASTER", "true")
        master = c.post(url, json=body, headers={
            "NGSILD-Tenant": "tenant-a", "X-Internal-Service-Secret": "dummy-secret"})
        assert master.status_code == 204


def test_registrar_passes_secret_and_flag(monkeypatch):
    """The registrar owns the receiver auth header; derived tokens follow the env flag."""
    from app.services.subscriptions import build_registrar

    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "dummy-secret")
    monkeypatch.delenv("NKZ_NOTIFY_DERIVED_TOKENS", raising=False)
    r = build_registrar()
    assert r.internal_secret == "dummy-secret" and r.derived_tokens is False
    assert r.notification_headers == {}
    monkeypatch.setenv("NKZ_NOTIFY_DERIVED_TOKENS", "true")
    assert build_registrar().derived_tokens is True
