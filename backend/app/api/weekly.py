"""Weekly farm report routes: latest report (card in the app), channels, operator run.

The operator run lives on its OWN router with its own secret check: the shared /internal router
authenticates Orion notifications and refuses the master secret in production.
"""
import hmac
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictBool

from app.config import get_settings
from app.digest.weekly import render, schedule, sources, store
from app.digest.weekly.texts import LANGS
from app.middleware import AuthContext, require_roles

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/weekly-report", tags=["weekly-report"])
internal_router = APIRouter(prefix="/internal/weekly-report", tags=["internal"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _lang(raw: str | None) -> str:
    if raw in LANGS:
        return raw
    default = get_settings().default_lang
    return default if default in LANGS else "es"


class ChannelsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: StrictBool
    zulip: StrictBool


@router.get("/latest")
def latest(lang: str | None = None, auth: AuthContext = Depends(require_roles("TenantAdmin", "TechnicalConsultant"))):
    tenant_id = auth.tenant_id
    row = store.get_report(tenant_id)
    if not row or row.get("status") in ("no_sources", "missed"):
        raise HTTPException(status_code=404, detail="No report this week")
    try:
        zone = schedule.pick_timezone(sources.parcel_timezones(tenant_id), get_settings().weekly_report_default_tz)
    except Exception as exc:  # noqa: BLE001 - zone unreadable: compare against UTC rather than fail
        logger.warning("weekly_report tenant=%s latest: timezone unavailable (%s), using UTC",
                       tenant_id, type(exc).__name__)
        zone = timezone.utc
    local = _now().astimezone(zone)
    current = schedule.iso_week(local.date() - timedelta(days=local.weekday()))
    content = row.get("content")
    if row.get("iso_week") != current or not isinstance(content, dict) or content.get("iso_week") != current \
            or content.get("status") == "no_sources":
        raise HTTPException(status_code=404, detail="No report this week")
    generated = row.get("generated_at")
    return {
        "reportId": row["iso_week"],
        "weekStart": row["week_start"].isoformat(),
        "status": content.get("status") or row.get("status"),
        "generatedAt": generated.isoformat() if generated else None,
        "plain": render.plain(content, _lang(lang)),
    }


@router.get("/channels")
def get_channels(auth: AuthContext = Depends(require_roles("TenantAdmin", "PlatformAdmin"))):
    return store.get_channels(auth.tenant_id)


@router.put("/channels")
def put_channels(body: ChannelsBody, auth: AuthContext = Depends(require_roles("TenantAdmin", "PlatformAdmin"))):
    store.set_channels(auth.tenant_id, body.email, body.zulip)
    return store.get_channels(auth.tenant_id)


class RunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    dry_run: StrictBool = True
    only_user_id: str | None = None
    zulip: StrictBool = False


def _check_secret(request: Request) -> None:
    secret = get_settings().internal_service_secret.encode()
    given = request.headers.get("X-Internal-Service-Secret", "").encode()
    if not secret or not hmac.compare_digest(given, secret):
        raise HTTPException(status_code=401, detail="Invalid or missing credentials")


@internal_router.post("/run", dependencies=[Depends(_check_secret)])
def run(body: RunBody):
    if not body.tenant_id.strip():
        raise HTTPException(status_code=400, detail="tenant_id required")
    now = _now()
    if body.dry_run:
        try:
            out = schedule.run_tenant(body.tenant_id, now=now, dry_run=True)
        except Exception as exc:  # noqa: BLE001
            logger.error("weekly_report tenant=%s dry run failed: %s", body.tenant_id, type(exc).__name__)
            raise HTTPException(status_code=502, detail="report could not be built")
        report = out["report"]
        mail = render.email(report, "es", None, get_settings().public_app_url or None)
        return {"dry_run": True, "report": report, "email": mail}
    if not body.only_user_id:
        raise HTTPException(status_code=400, detail="only_user_id is required unless dry_run")
    try:
        out = schedule.run_manual(body.tenant_id, now=now, only_user_id=body.only_user_id,
                                  include_zulip=body.zulip)
    except Exception as exc:  # noqa: BLE001
        logger.error("weekly_report tenant=%s manual run failed: %s", body.tenant_id, type(exc).__name__)
        raise HTTPException(status_code=502, detail="report could not be built")
    return {"dry_run": False, **out}
