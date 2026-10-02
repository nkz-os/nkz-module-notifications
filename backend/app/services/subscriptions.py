"""Registro idempotente de la suscripción Orion-LD a Alert.

Las notificaciones son capacidad de plataforma: la suscripción se registra en
TODOS los tenants activos (la entrega solo ocurre donde el tenant configura
canales). El SDK >=0.8.5 hace PATCH sobre 409 y reactiva suscripciones pausadas.
"""

import asyncio
import logging
import os

from nkz_platform_sdk.subscriptions import SubscriptionRegistrar

from app.config import get_settings
from app.db import get_conn

logger = logging.getLogger(__name__)

MODULE_NAME = "notifications"
ALERT_THROTTLING = 15


def active_tenants() -> list[str]:
    """Todos los tenants activos (las notificaciones no son opt-in por módulo)."""
    settings = get_settings()
    if not settings.postgres_url:
        logger.error("POSTGRES_URL not set — cannot resolve tenants for subscriptions")
        return []
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT tenant_id FROM tenants "
                "WHERE status = 'active' AND tenant_id IS NOT NULL AND tenant_id <> ''"
            )
            return sorted(r["tenant_id"] for r in cur.fetchall())
    except Exception as exc:  # noqa: BLE001
        logger.warning("active tenants query failed: %s", exc)
        return []
    finally:
        conn.close()


def build_registrar() -> SubscriptionRegistrar | None:
    settings = get_settings()
    secret = os.getenv("INTERNAL_SERVICE_SECRET", "") or settings.internal_service_secret
    if not secret:
        logger.error(
            "INTERNAL_SERVICE_SECRET not set — subscriptions NOT registered; "
            "/internal/notify receives nothing"
        )
        return None
    return SubscriptionRegistrar(
        orion_url=settings.orion_ld_url,
        notification_url=(
            f"http://notifications-api-service:8000{settings.api_prefix}/internal/notify"
        ),
        subscriptions=[
            {"type": "Alert", "watched_attributes": ["status"], "throttling": ALERT_THROTTLING},
        ],
        module_name=MODULE_NAME,
        context_url=settings.context_url,
        notification_headers={"X-Internal-Service-Secret": secret},
    )


async def _active_tenants_async() -> list[str]:
    return await asyncio.to_thread(active_tenants)


async def reconcile_once(registrar: SubscriptionRegistrar) -> dict | None:
    try:
        tenants = await _active_tenants_async()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Subscription reconcile skipped, tenant lookup failed: %s", exc)
        return None
    result = await registrar.ensure_all(tenants)
    logger.info(
        "Subscriptions reconciled for %s: created=%d converged=%d skipped=%d errors=%d",
        tenants,
        result["created"],
        result.get("converged", 0),
        result.get("skipped", 0),
        len(result["errors"]),
    )
    for error in result["errors"]:
        logger.warning("Subscription reconcile error: %s", error)
    return result


async def run_subscription_reconciler(interval_minutes: int = 60) -> None:
    registrar = build_registrar()
    if registrar is None:
        return
    try:
        await reconcile_once(registrar)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Initial subscription reconcile failed: %s", exc)
    await registrar.periodic_heal(_active_tenants_async, interval_minutes=interval_minutes)
