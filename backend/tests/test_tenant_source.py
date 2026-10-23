"""The module reads tenants through the platform view, never the core table."""

from unittest.mock import MagicMock, patch

import pytest
from app.api import internal
from app.services import subscriptions


def _fake_conn(rows):
    cur = MagicMock()
    cur.fetchall.return_value = rows
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    return conn, cur


def _sql(cur) -> str:
    return " ".join(str(c.args[0]) for c in cur.execute.call_args_list)


def test_active_tenants_reads_the_plan_view():
    conn, cur = _fake_conn([{"tenant_id": "tenant-a"}])
    with patch.object(subscriptions, "get_conn", return_value=conn):
        assert subscriptions.active_tenants() == ["tenant-a"]
    assert "module_tenant_plan" in _sql(cur)
    assert "FROM tenants" not in _sql(cur)


@pytest.mark.parametrize("call", ["resolve", "parcel_names"])
def test_internal_tenant_lookups_read_the_plan_view(call):
    conn, cur = _fake_conn([])
    with patch.object(internal, "get_conn", return_value=conn):
        if call == "resolve":
            internal._resolve_tenant_for_entity(conn, "urn:ngsi-ld:AgriParcel:p1")
        else:
            internal._parcel_names()
    assert "module_tenant_plan" in _sql(cur)
    assert "FROM tenants" not in _sql(cur)
