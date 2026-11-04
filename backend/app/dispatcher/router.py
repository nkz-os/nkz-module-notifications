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

# Non-weather types that are also delivered immediately (severity gate still applies).
IMMEDIATE_ALERT_TYPES = {
    "route_planned",
}

# Neutral English titles for types that have one; others use the generic title.
_ALERT_TITLES = {
    "route_planned": "Route planned",
}

_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _unwrap(value):
    """Extrae el valor de un Property/Relationship normalizado, o el valor crudo."""
    if isinstance(value, dict):
        return value.get("value", value.get("object"))
    return value


SUPPORTED_LANGS = ("es", "eu", "en")
_URGENCIES = ("vibrate", "silent")
_PARCEL_PREFIX = "urn:ngsi-ld:AgriParcel:"


def _unwrap_obj(value):
    """Como _unwrap, pero admite que el valor crudo sea ya un dict (plain/action)."""
    if isinstance(value, dict) and value.get("type") == "Property":
        return value.get("value")
    return value


def _clean_plain(value) -> dict | None:
    """{es,eu,en} -> {lang: {title, body}} con solo entradas válidas; None si no hay ninguna."""
    if not isinstance(value, dict):
        return None
    out = {}
    for lang in SUPPORTED_LANGS:
        t = value.get(lang)
        if isinstance(t, dict) and isinstance(t.get("title"), str) and isinstance(t.get("body"), str):
            out[lang] = {"title": t["title"], "body": t["body"]}
    return out or None


def pick_lang(plain: dict, lang: str) -> dict | None:
    """plain[lang] -> plain['es'] -> primero disponible -> None."""
    if not isinstance(plain, dict) or not plain:
        return None
    return plain.get(lang) or plain.get("es") or next(iter(plain.values()), None)


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

    description = _unwrap(entity.get("description"))
    description = str(description).strip() if description else ""

    plain = _clean_plain(_unwrap_obj(entity.get("plain")))
    urgency = _unwrap(entity.get("urgency"))
    if urgency not in _URGENCIES or plain is None:
        # vibrate requires valid plain texts; without them: legacy behavior.
        urgency = None
    action = _unwrap_obj(entity.get("action"))
    if not (isinstance(action, dict) and isinstance(action.get("kind"), str)):
        action = None
    entity_id = str(entity_id) if entity_id else ""

    return {
        "id": alert_id,
        "alert_type": str(alert_type),
        "severity": severity,
        "entity_id": entity_id,
        "description": description,
        "plain": plain,
        "urgency": urgency,
        "action": action,
        "parcel_id": entity_id if entity_id.startswith(_PARCEL_PREFIX) else None,
    }


def _is_immediate(info: dict) -> bool:
    urgency = info.get("urgency")
    if urgency == "vibrate":
        return True
    if urgency == "silent":
        return False
    settings = get_settings()
    min_sev = _SEVERITY_ORDER.get(settings.immediate_min_severity, 2)
    return (
        (info["alert_type"] in EXTREME_ALERT_TYPES or info["alert_type"] in IMMEDIATE_ALERT_TYPES)
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
        # Resolved/expired/dismissed: release the dedup so a later episode of the
        # same (stable) alert id notifies again.
        if isinstance(entity, dict) and entity.get("id") and (_unwrap(entity.get("status")) or "active") != "active":
            NotificationDispatcher().release_delivery(tenant_id, str(entity["id"]))
        return "skipped"

    if _is_immediate(info):
        urgency = info.get("urgency")
        parcel_id = info.get("parcel_id")
        dispatcher = NotificationDispatcher()
        if dispatcher.has_delivered(info["id"], info["severity"]):
            return "skipped"
        dispatcher.dispatch(
            tenant_id,
            info["alert_type"],
            info["severity"],
            {
                "id": info["id"],
                "title": _ALERT_TITLES.get(info["alert_type"], f"Notification — {info['alert_type']}"),
                "summary": info.get("description")
                or f"[{info['severity'].upper()}] {info['alert_type']}: {info['entity_id']}",
                "data": {
                    "alertType": info["alert_type"],
                    "entityId": info["entity_id"],
                    "parcelId": parcel_id,
                    "plain": None,
                    **({"urgency": urgency} if urgency else {}),
                    **({"action": info["action"]} if info.get("action") else {}),
                    "screen": "ParcelDetail" if parcel_id else None,
                    "params": {"parcelId": parcel_id} if parcel_id else {},
                },
                # Legacy alerts (no valid plain): no channel, exactly as before.
                **({"channel_id": urgency} if urgency else {}),
                "plain_all": info.get("plain"),
            },
        )
        return "immediate"

    _queue_for_digest(tenant_id, info, alert_name or info.get("description", ""), parcel_name)
    return "queued"
