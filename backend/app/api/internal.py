"""
Notifications Backend - Internal Routes

`/internal/notify` es el receptor de notificaciones NGSI-LD de Orion (Alert).
Autenticado por X-Internal-Service-Secret (inyectado como receiverInfo en la
suscripción). Responde 204 al momento y procesa en segundo plano.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from app.db import get_conn
from app.middleware import verify_internal_secret

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(verify_internal_secret)])


def _unwrap(value):
    if isinstance(value, dict):
        return value.get("value", value.get("object"))
    return value


def _resolve_tenant_for_entity(conn, entity_id: str) -> str | None:
    """Fallback: busca en qué tenant vive la entidad (si Orion no envió el header)."""
    from nkz_platform_sdk import SyncOrionClient

    from app.config import get_settings

    settings = get_settings()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT tenant_id FROM tenants "
                "WHERE status = 'active' AND tenant_id IS NOT NULL"
            )
            tenants = [r["tenant_id"] for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        logger.warning("tenant list failed: %s", exc)
        return None

    for tenant in tenants:
        try:
            with SyncOrionClient(
                tenant, base_url=settings.orion_ld_url, context_url=settings.context_url
            ) as orion:
                if orion.get_entity(entity_id):
                    return tenant
        except Exception:  # noqa: BLE001
            continue
    return None


def _parcel_names() -> dict[str, dict[str, str]]:
    """Mapa tenant -> {parcela URN -> name}, en una consulta por tenant activo."""
    from nkz_platform_sdk import SyncOrionClient

    from app.config import get_settings

    settings = get_settings()
    out: dict[str, dict[str, str]] = {}
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT tenant_id FROM tenants "
                "WHERE status = 'active' AND tenant_id IS NOT NULL"
            )
            tenants = [r["tenant_id"] for r in cur.fetchall()]
    except Exception:  # noqa: BLE001
        return out
    finally:
        conn.close()

    for tenant in tenants:
        try:
            with SyncOrionClient(
                tenant, base_url=settings.orion_ld_url, context_url=settings.context_url
            ) as orion:
                parcels = orion.query_entities(type="AgriParcel", limit=1000)
            names = {}
            for p in parcels:
                pid = p.get("id")
                name = p.get("name")
                if isinstance(name, dict):
                    name = name.get("value")
                if pid and name:
                    names[pid] = name
            out[tenant] = names
        except Exception:  # noqa: BLE001
            continue
    return out


def _process_alert_background(tenant_hint: str | None, entity: dict, names_by_tenant: dict) -> None:
    """Procesa una Alert en segundo plano: inmediata o cola de digest."""
    from app.dispatcher.router import handle_alert

    conn = get_conn()
    try:
        tenant_id = tenant_hint or _resolve_tenant_for_entity(conn, entity.get("id"))
        if not tenant_id:
            logger.warning("notify: cannot resolve tenant for alert %s", entity.get("id"))
            return
        parcel_names = names_by_tenant.get(tenant_id, {})
        ref = _unwrap(entity.get("refEntity"))
        parcel_name = parcel_names.get(str(ref) if ref else "", "")
        outcome = handle_alert(tenant_id, entity, parcel_name=parcel_name)
        logger.info("notify: alert %s -> %s", entity.get("id"), outcome)
    except Exception as exc:  # noqa: BLE001
        logger.warning("notify: alert processing failed %s: %s", entity.get("id"), exc)
    finally:
        conn.close()


@router.post("/notify", status_code=204)
async def ngsi_ld_notify(
    request: Request,
    x_ngsild_tenant: str | None = Header(None, alias="NGSILD-Tenant"),
):
    """Recibe notificaciones NGSI-LD (Alert) y procesa en segundo plano.

    Contrato Orion-LD: responder 204 SIN esperar. El trabajo corre en un hilo.
    """
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="invalid JSON")

    data = payload.get("data")
    if not isinstance(data, list):
        raise HTTPException(status_code=400, detail="invalid payload")

    alerts = [e for e in data if isinstance(e, dict) and e.get("type") == "Alert" and e.get("id")]
    if not alerts:
        return Response(status_code=204)

    def _background():
        names_by_tenant = _parcel_names()
        for entity in alerts:
            _process_alert_background(x_ngsild_tenant, entity, names_by_tenant)

    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, _background)

    return Response(status_code=204)
