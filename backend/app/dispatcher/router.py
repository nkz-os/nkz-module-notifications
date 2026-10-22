"""Router de Alert: decide entre entrega inmediata o cola de digest.

Inmediatas: meteorológicas extremas (`EXTREME_ALERT_TYPES`) con severidad
high/critical → NotificationDispatcher al momento.

Resto: INSERT en `notifications.digest_queue` (dedup por
(tenant, alert_id, severity, digest_date)) — el digest sender las agrupa.
"""
import logging

from app.config import get_settings
from app.db import get_conn

logger = logging.getLogger(__name__)

# Meteorológicas extremas (o similar): entrega individual inmediata.
EXTREME_ALERT_TYPES = {
    "frost",
    "hail_proxy",
    "heat_stress",
    "wind_damage",
    "fire_30_30_30",
    "weather_alert",
}

_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _unwrap(value):
    """Extrae el valor de un Property/Relationship normalizado, o el valor crudo."""
    if isinstance(value, dict):
        return value.get("value", value.get("object"))
    return value


def alert_to_info(entity: dict) -> dict | None:
    """Normaliza una Alert NGSI-LD (de cualquier productor) a info de entrega."""
    if not isinstance(entity, dict):
        return None
    alert_id = entity.get("id")
    if not alert_id:
        return None

    status = _unwrap(entity.get("status")) or "active"
    if status != "active":
        return None

    alert_type = _unwrap(entity.get("alertType"))
    if not alert_type:
        alert_type = entity.get("type") or alert_id.split(":")[-1] or "unknown"
    severity = str(_unwrap(entity.get("severity")) or "medium").lower()
    if severity not in _SEVERITY_ORDER:
        severity = "medium"
    entity_id = _unwrap(entity.get("refEntity")) or ""

    return {
        "id": alert_id,
        "alert_type": str(alert_type),
        "severity": severity,
        "entity_id": str(entity_id) if entity_id else "",
    }


def _is_immediate(info: dict) -> bool:
    settings = get_settings()
    min_sev = _SEVERITY_ORDER.get(settings.immediate_min_severity, 2)
    return (
        info["alert_type"] in EXTREME_ALERT_TYPES
        and _SEVERITY_ORDER.get(info["severity"], 0) >= min_sev
    )


def _queue_for_digest(tenant_id: str, info: dict, alert_name: str = "", parcel_name: str = "") -> bool:
    """INSERT con dedup diario. True si entró nueva; False si ya estaba hoy."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO notifications.digest_queue
                    (tenant_id, alert_id, alert_type, alert_name, severity, parcel_name)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, alert_id, severity, digest_date) DO NOTHING
                """,
                (tenant_id, info["id"], info["alert_type"], alert_name, info["severity"], parcel_name),
            )
        conn.commit()
        return cur.rowcount > 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("digest queue insert failed %s: %s", info["id"], exc)
        return False
    finally:
        conn.close()


def handle_alert(tenant_id: str, entity: dict, alert_name: str = "", parcel_name: str = "") -> str:
    """Procesa una Alert: 'immediate', 'queued' o 'skipped'."""
    from app.dispatcher import NotificationDispatcher

    info = alert_to_info(entity)
    if not info:
        return "skipped"

    if _is_immediate(info):
        dispatcher = NotificationDispatcher()
        if dispatcher.has_delivered(info["id"], info["severity"]):
            return "skipped"
        dispatcher.dispatch(
            tenant_id,
            info["alert_type"],
            info["severity"],
            {
                "id": info["id"],
                "title": f"Notification — {info['alert_type']}",
                "summary": f"[{info['severity'].upper()}] {info['alert_type']}: {info['entity_id']}",
                "data": {"alertType": info["alert_type"], "entityId": info["entity_id"]},
            },
        )
        return "immediate"

    _queue_for_digest(tenant_id, info, alert_name, parcel_name)
    return "queued"
