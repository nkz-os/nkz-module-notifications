"""Tests for role-based authorization on channels endpoints."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.channels import _DEFAULTS
from app.main import app

_MOCK_ROW = {
    **_DEFAULTS,
    "email": {"enabled": True, "to": "alerts@example.com"},
}


@pytest.fixture()
def mock_db():
    with patch("app.api.channels.get_conn") as mock_conn:
        cursor = MagicMock()
        cursor.fetchone.return_value = _MOCK_ROW
        mock_conn.return_value.cursor.return_value.__enter__.return_value = cursor
        yield mock_conn


def test_put_channels_farmer_forbidden():
    with TestClient(app) as client:
        res = client.put(
            "/api/notifications/channels",
            json={"email": {"enabled": True}},
            headers={
                "X-Tenant-ID": "test-tenant",
                "X-User-ID": "farmer-user",
                "X-User-Roles": "Farmer",
            },
        )
        assert res.status_code == 403
        assert "Access denied" in res.json().get("detail", "")


def test_put_channels_tenant_admin_allowed(mock_db):
    with TestClient(app) as client:
        res = client.put(
            "/api/notifications/channels",
            json={"email": {"enabled": True, "to": "alerts@example.com"}},
            headers={
                "X-Tenant-ID": "test-tenant",
                "X-User-ID": "admin-user",
                "X-User-Roles": "TenantAdmin",
            },
        )
        assert res.status_code == 200
        assert res.json()["email"] == {"enabled": True, "to": "alerts@example.com"}
        cursor = mock_db.return_value.cursor.return_value.__enter__.return_value
        assert all(c.args[1][0] == "test-tenant" for c in cursor.execute.call_args_list)


def test_put_channels_platform_admin_allowed(mock_db):
    with TestClient(app) as client:
        res = client.put(
            "/api/notifications/channels",
            json={"email": {"enabled": True, "to": "alerts@example.com"}},
            headers={
                "X-Tenant-ID": "test-tenant",
                "X-User-ID": "platform-user",
                "X-User-Roles": "PlatformAdmin",
            },
        )
        assert res.status_code == 200
        assert res.json()["email"] == {"enabled": True, "to": "alerts@example.com"}


def test_get_channels_farmer_allowed(mock_db):
    with TestClient(app) as client:
        res = client.get(
            "/api/notifications/channels",
            headers={
                "X-Tenant-ID": "test-tenant",
                "X-User-ID": "farmer-user",
                "X-User-Roles": "Farmer",
            },
        )
        assert res.status_code == 200
        assert "email" in res.json()
