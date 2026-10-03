"""Config multicanal por tenant (esquema notifications.tenant_alert_channels)."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from psycopg2.extras import Json

from app.db import get_conn
from app.middleware import AuthContext, get_tenant_id, require_roles

router = APIRouter()

_DEFAULTS = {
    "email": {"enabled": False},
    "push": {"enabled": False},
    "zulip": {"enabled": False},
    "webhook": {"enabled": False, "targets": []},
    "telegram": {"enabled": False},
}


class ChannelsIn(BaseModel):
    email: dict | None = None
    push: dict | None = None
    zulip: dict | None = None
    webhook: dict | None = None
    telegram: dict | None = None


@router.get("/channels")
def get_channels(tenant_id: str = Depends(get_tenant_id)):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT email, push, zulip, webhook, telegram "
                "FROM notifications.tenant_alert_channels WHERE tenant_id=%s",
                (tenant_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else _DEFAULTS
    finally:
        conn.close()


@router.put("/channels")
def put_channels(
    body: ChannelsIn,
    auth: AuthContext = Depends(require_roles("TenantAdmin", "PlatformAdmin")),
):
    tenant_id = auth.tenant_id
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT email, push, zulip, webhook, telegram "
                "FROM notifications.tenant_alert_channels WHERE tenant_id=%s",
                (tenant_id,),
            )
            row = cur.fetchone()
            current = dict(row) if row else {**_DEFAULTS}
            merged = {}
            dumped = body.model_dump()
            for k in _DEFAULTS:
                val = dumped.get(k)
                merged[k] = val if val is not None else current[k]
            cur.execute(
                """
                INSERT INTO notifications.tenant_alert_channels
                    (tenant_id, email, push, zulip, webhook, telegram)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id) DO UPDATE SET
                    email=EXCLUDED.email, push=EXCLUDED.push, zulip=EXCLUDED.zulip,
                    webhook=EXCLUDED.webhook, telegram=EXCLUDED.telegram, updated_at=now()
                RETURNING email, push, zulip, webhook, telegram
                """,
                (tenant_id, Json(merged["email"]), Json(merged["push"]), Json(merged["zulip"]),
                 Json(merged["webhook"]), Json(merged["telegram"])),
            )
            conn.commit()
            return dict(cur.fetchone())
    finally:
        conn.close()
