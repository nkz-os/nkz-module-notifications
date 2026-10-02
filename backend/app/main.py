"""
Notifications Backend — FastAPI Application.

Único camino de entrega de avisos de la plataforma: se suscribe a Alert en
Orion y entrega por canales (email/push/zulip/telegram), con digest agrupado
diario e inmediatas para meteorológicas extremas.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings, require_postgres_url
from app.api import router as api_router
from app.api.internal import router as internal_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: reconciliador de suscripciones + digest sender."""
    settings = get_settings()
    logger.info("%s v%s starting — prefix=%s", settings.app_name, settings.app_version, settings.api_prefix)
    
    # Fail-fast validations
    require_postgres_url()
    if not settings.internal_service_secret:
        logger.critical("CRITICAL: INTERNAL_SERVICE_SECRET is empty. Callbacks will fail with 401.")

    from app.digest.sender import run_digest_sender
    from app.services.subscriptions import run_subscription_reconciler

    reconciler_task = asyncio.create_task(run_subscription_reconciler())
    digest_task = asyncio.create_task(run_digest_sender())

    yield

    for task in (reconciler_task, digest_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    logger.info("%s shutting down", settings.app_name)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Notifications - alert delivery for Nekazari Platform",
        docs_url=f"{settings.api_prefix}/docs",
        redoc_url=f"{settings.api_prefix}/redoc",
        openapi_url=f"{settings.api_prefix}/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "service": settings.app_name, "version": settings.app_version}

    app.include_router(api_router, prefix=settings.api_prefix)
    app.include_router(internal_router, prefix=settings.api_prefix)

    return app


app = create_app()
