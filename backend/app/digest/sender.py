"""Digest sender — agrupa los avisos acumulados y envía 1 email por tenant.

Corre como tarea periódica (asyncio, cada DIGEST_INTERVAL_HOURS). Para cada
tenant con ítems no enviados y email habilitado: email agrupado y marca
`sent_at`.
"""
import asyncio
import logging

from app.config import get_settings
from app.db import get_conn

logger = logging.getLogger(__name__)

_SEV_LABEL = {"critical": "CRÍTICO", "high": "ALTO", "medium": "MEDIO", "low": "BAJO"}
_SEV_ORDER_KEY = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _build_message(items: list[dict]) -> str:
    """Cuerpo del digest: 'N avisos activos' + lista legible."""
    lines = [f"{len(items)} avisos activos:", ""]
    for it in items:
        name = it.get("alert_name") or it.get("alert_type", "?")
        parcel = it.get("parcel_name") or ""
        sev = _SEV_LABEL.get(it.get("severity", ""), it.get("severity", ""))
        where = f" — {parcel}" if parcel else ""
        lines.append(f"• [{sev}] {name}{where}")
    lines.append("")
    lines.append("(resumen agrupado; los avisos críticos llegan aparte y al momento)")
    return "\n".join(lines)


def send_digest_once() -> dict:
    """Una pasada del digest. Nunca lanza. Returns {'tenants': n, 'sent': m}."""
    from app.dispatcher import NotificationDispatcher

    sent = tenants = 0
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT tenant_id FROM notifications.digest_queue
                WHERE sent_at IS NULL
                """
            )
            tenant_rows = cur.fetchall()
    finally:
        conn.close()

    dispatcher = NotificationDispatcher()
    for row in tenant_rows:
        tenant_id = row["tenant_id"]
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT alert_type, alert_name, severity, parcel_name
                    FROM notifications.digest_queue
                    WHERE tenant_id = %s AND sent_at IS NULL
                    ORDER BY severity, alert_type
                    """,
                    (tenant_id,),
                )
                items = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
        if not items:
            continue

        items.sort(key=lambda x: _SEV_ORDER_KEY.get(x.get("severity", ""), 9))
        message = _build_message(items)
        results = dispatcher.dispatch_digest(tenant_id, "Avisos del día (resumen)", message)
        ok = any(r.get("status") == "sent" for r in results)
        tenants += 1
        if ok:
            sent += 1
            conn = get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE notifications.digest_queue SET sent_at = now() "
                        "WHERE tenant_id = %s AND sent_at IS NULL",
                        (tenant_id,),
                    )
                conn.commit()
            finally:
                conn.close()
        else:
            logger.warning("digest send failed for %s: %s", tenant_id, results)

    logger.info("digest pass: tenants=%d sent=%d", tenants, sent)
    return {"tenants": tenants, "sent": sent}


async def run_digest_sender(interval_hours: int | None = None) -> None:
    """Digest ahora, luego cada interval_hours. Nunca lanza."""
    settings = get_settings()
    interval = (interval_hours or settings.digest_interval_hours) * 3600
    while True:
        try:
            await asyncio.to_thread(send_digest_once)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("digest pass failed: %s", exc)
        await asyncio.sleep(interval)
