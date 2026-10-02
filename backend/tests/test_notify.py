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
                    headers={"NGSILD-Tenant": "montiko"},
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
                    headers={"NGSILD-Tenant": "montiko"},
                )
                assert r.status_code == 204
        finally:
            app.dependency_overrides.pop(verify_internal_secret, None)
