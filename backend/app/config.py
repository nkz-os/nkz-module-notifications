"""Notifications Backend — configuración."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Notifications"
    app_version: str = "1.0.0"
    debug: bool = False
    log_level: str = "INFO"

    api_prefix: str = "/api/notifications"
    cors_origins: list[str] = []

    # Internal service-to-service auth (Orion notify, in-cluster callers).
    internal_service_secret: str = ""

    # PostgreSQL (channels, deliveries, digest queue).
    postgres_url: str = ""

    # Orion-LD
    orion_ld_url: str = "http://orion-ld-service:1026"
    context_url: str = "http://api-gateway-service:5000/ngsi-ld-context.json"

    # Channel transports
    email_service_url: str = "http://email-service:5000"
    push_service_url: str = "http://push-notification-service:5000"
    zulip_service_url: str = "http://zulip-module-service:5000"

    # Digest: intervalo del sender (h) y umbral de severidad de las inmediatas.
    digest_interval_hours: int = 12
    immediate_min_severity: str = "high"

    # Idioma por defecto de los avisos llanos (es|eu|en).
    default_lang: str = "es"

    # Weekly report: dedicated secret for the public preferences token (never HMAC_SECRET).
    report_prefs_secret: str = ""
    public_api_url: str = ""
    public_app_url: str = ""
    weekly_report_enabled: bool = False
    weekly_report_default_tz: str = "UTC"
    tenant_user_api_url: str = "http://tenant-user-api-service:5000"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()


def require_postgres_url() -> str:
    """POSTGRES_URL obligatorio — sin fallback (regla de plataforma)."""
    settings = get_settings()
    if not settings.postgres_url:
        raise RuntimeError(
            "POSTGRES_URL is not set. Set the POSTGRES_URL env var (no fallback allowed)."
        )
    return settings.postgres_url
