"""PUT /channels validates push.lang."""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api.channels import _DEFAULTS
from app.main import app

H = {"X-Tenant-ID": "acmefarm", "X-User-ID": "u", "X-User-Roles": "TenantAdmin"}


def _put(push):
    with patch("app.api.channels.get_conn") as gc:
        cur = MagicMock()
        cur.fetchone.return_value = {**_DEFAULTS}
        gc.return_value.cursor.return_value.__enter__.return_value = cur
        with TestClient(app) as c:
            return c.put("/api/notifications/channels", json={"push": push}, headers=H)


def test_invalid_lang_422():
    assert _put({"enabled": True, "lang": "xx"}).status_code == 422


def test_valid_lang_ok():
    assert _put({"enabled": True, "lang": "eu"}).status_code == 200


def test_no_lang_ok():
    assert _put({"enabled": True}).status_code == 200
