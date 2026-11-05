"""Weekly report scheduling (spec 4, 8): when to build, save and send, and the loop that drives it.

`decide` is pure. Everything else is I/O around it. Nothing ever goes out on a Tuesday: outside
Monday 07:00-20:00 local the decision is NOTHING (or MISS when the day ended with nothing sent).
"""
import asyncio
import logging
import time
from collections import Counter
from datetime import date, datetime, time as dtime, timedelta, timezone
from enum import Enum
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.services.subscriptions import active_tenants

from . import compose, deliver, sources, store

logger = logging.getLogger(__name__)

INTERVAL_S = 600
SEND_FROM = dtime(7, 0)
PARTIAL_FROM = dtime(9, 0)
MISS_FROM = dtime(20, 0)
_PURGE_EVERY_S = 86400


class Action(Enum):
    WAIT = "WAIT"            # not yet; with build_status=None it means "build first, then decide again"
    SEND = "SEND"            # save, deliver, mark delivered when every delivery went through
    SAVE_ONLY = "SAVE_ONLY"  # save (card in the app), send nothing
    REFRESH = "REFRESH"      # save the completed report, do not resend
    MISS = "MISS"            # window over and nothing went out
    NOTHING = "NOTHING"


def iso_week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def pick_timezone(zones: list[str], default: str) -> ZoneInfo:
    """Most frequent valid IANA zone (ties: alphabetical); otherwise the default, otherwise UTC."""
    valid = []
    for z in zones or []:
        try:
            ZoneInfo(z)
        except Exception:  # noqa: BLE001 - unknown, malformed or path-like names are ignored
            continue
        valid.append(z)
    if valid:
        counts = Counter(valid)
        best = min(counts, key=lambda z: (-counts[z], z))
        return ZoneInfo(best)
    try:
        return ZoneInfo(default)
    except Exception:  # noqa: BLE001
        logger.error("weekly_report: invalid WEEKLY_REPORT_DEFAULT_TZ, using UTC")
        return ZoneInfo("UTC")


def decide(*, local_now: datetime, status: str | None, delivered: bool, build_status: str | None) -> Action:
    """Pure. `status`/`delivered`: the stored report of THIS week (None/False when none).
    `build_status`: status of a freshly composed report, None if not built yet."""
    if local_now.weekday() != 0 or local_now.time() < SEND_FROM:
        return Action.NOTHING
    if status in ("no_sources", "missed"):
        return Action.NOTHING  # decided already; never rebuilt this week
    if local_now.time() >= MISS_FROM:
        return Action.NOTHING if delivered else Action.MISS
    if delivered and status == "complete":
        return Action.NOTHING
    if build_status is None:
        return Action.WAIT
    if delivered:  # delivered as partial: only an improvement is worth saving, never resent
        return Action.REFRESH if build_status == "complete" else Action.NOTHING
    if build_status == "complete":
        return Action.SEND
    if build_status == "no_sources":
        return Action.SAVE_ONLY
    if build_status == "partial":
        return Action.SEND if local_now.time() >= PARTIAL_FROM else Action.WAIT
    return Action.WAIT  # all_failed, or an unknown status: never send blind


def in_scan_window(now: datetime) -> bool:
    """Sunday 10:00 UTC to Tuesday 08:00 UTC: Monday 07:00 in UTC+14 .. Monday 20:00 in UTC-12, with margin."""
    now = now.astimezone(timezone.utc)
    wd = now.weekday()
    if wd == 6:
        return now.hour >= 10
    if wd == 0:
        return True
    return wd == 1 and now.hour < 8


def _log(tenant_id, week, status, action, **extra):
    tail = "".join(f" {k}={v}" for k, v in extra.items())
    logger.info("weekly_report tenant=%s week=%s status=%s action=%s%s", tenant_id, week, status, action, tail)


def _mondays_near(now: datetime) -> set[date]:
    u = now.astimezone(timezone.utc)
    days = {(u + timedelta(hours=h)).date() for h in (-12, 0, 14)}
    return {d for d in days if d.weekday() == 0}


def _finished(row: dict | None, now: datetime) -> bool:
    """Cheap check, no zone needed: this week's report is delivered, or was decided not to be sent."""
    if not row:
        return False
    ws = row.get("week_start")
    if isinstance(ws, datetime):
        ws = ws.date()
    if ws not in _mondays_near(now):
        return False
    if row.get("status") in ("no_sources", "missed"):
        return True
    return row.get("delivered_at") is not None and row.get("status") != "partial"  # partial may still complete


def _zone(tenant_id: str) -> ZoneInfo:
    return pick_timezone(sources.parcel_timezones(tenant_id), get_settings().weekly_report_default_tz)


def _build(tenant_id: str, week_start: date, wk: str) -> dict:
    return compose.build(sources.gather(tenant_id, week_start), week_start, wk)


def run_tenant(tenant_id: str, *, now: datetime, dry_run: bool = False) -> dict:
    """One scheduler step for one tenant. With dry_run: build and return the report, write and send nothing."""
    if dry_run:
        try:
            zone = _zone(tenant_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("weekly_report tenant=%s dry run: timezone unavailable (%s), using default",
                           tenant_id, type(exc).__name__)
            zone = pick_timezone([], get_settings().weekly_report_default_tz)
        local = now.astimezone(zone)
        week_start = local.date() - timedelta(days=local.weekday())
        report = _build(tenant_id, week_start, iso_week(week_start))
        return {"action": "DRY", "report": report}

    row = store.get_report(tenant_id)
    if _finished(row, now):
        return {"action": Action.NOTHING.value, "reason": "finished"}
    try:
        zone = _zone(tenant_id)
    except Exception as exc:  # noqa: BLE001 - Orion down: skip this pass, retry in the next
        logger.warning("weekly_report tenant=%s action=SKIP timezone unavailable: %s", tenant_id, type(exc).__name__)
        return {"action": "SKIP", "reason": "timezone_unavailable"}
    local = now.astimezone(zone)
    week_start = local.date() - timedelta(days=local.weekday())
    wk = iso_week(week_start)
    same = bool(row) and row.get("iso_week") == wk
    status = row.get("status") if same else None
    delivered = same and row.get("delivered_at") is not None

    if local.weekday() == 0 and local.time() >= MISS_FROM and not delivered and store.has_sent_delivery(tenant_id, wk):
        store.mark_delivered(tenant_id, wk)  # it reached someone; failures stay in the log
        delivered = True
        _log(tenant_id, wk, status, "MARK_DELIVERED")

    action = decide(local_now=local, status=status, delivered=delivered, build_status=None)
    if action is Action.MISS:
        store.mark_missed(tenant_id, wk, week_start)
        logger.error("weekly_report tenant=%s week=%s status=%s action=MISS nothing was sent", tenant_id, wk, status)
        return {"action": action.value, "week": wk}
    if action is not Action.WAIT:
        return {"action": action.value, "week": wk}

    report = _build(tenant_id, week_start, wk)
    build_status = report["status"]
    action = decide(local_now=local, status=status, delivered=delivered, build_status=build_status)
    out = {"action": action.value, "week": wk, "status": build_status}
    if action in (Action.SEND, Action.SAVE_ONLY, Action.REFRESH):
        store.save_report(tenant_id, wk, week_start, build_status, report)  # saved before any delivery
    if action is Action.SEND:
        try:
            ok = deliver.deliver(tenant_id, report, include_zulip=True)
            if ok:
                store.mark_delivered(tenant_id, wk)
            out["delivered"] = bool(ok)
        except Exception as exc:  # noqa: BLE001 - the report stays saved; the next pass retries
            logger.error("weekly_report tenant=%s week=%s delivery raised %s", tenant_id, wk, type(exc).__name__)
            out["delivered"] = False
    _log(tenant_id, wk, build_status, action.value)
    return out


def run_manual(tenant_id: str, *, now: datetime, only_user_id: str, include_zulip: bool = False) -> dict:
    """Operator run: save the report (the card shows) and deliver to ONE user. Never marks the week delivered."""
    try:
        zone = _zone(tenant_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("weekly_report tenant=%s manual run: timezone unavailable (%s), using default",
                       tenant_id, type(exc).__name__)
        zone = pick_timezone([], get_settings().weekly_report_default_tz)
    local = now.astimezone(zone)
    week_start = local.date() - timedelta(days=local.weekday())
    wk = iso_week(week_start)
    report = _build(tenant_id, week_start, wk)
    status = report["status"]
    if status in ("no_sources", "all_failed"):
        _log(tenant_id, wk, status, "MANUAL_SKIP")
        return {"sent": False, "status": status, "iso_week": wk}
    store.save_report(tenant_id, wk, week_start, status, report)
    ok = deliver.deliver(tenant_id, report, only_user_id=only_user_id, include_zulip=include_zulip)
    _log(tenant_id, wk, status, "MANUAL_SEND", ok=ok)
    return {"sent": bool(ok), "status": status, "iso_week": wk}


def run_once(now: datetime) -> dict:
    """One pass over every active tenant. One tenant failing never stops the others."""
    if not get_settings().weekly_report_enabled or not in_scan_window(now):
        return {}
    out = {}
    for tenant in active_tenants():
        try:
            out[tenant] = run_tenant(tenant, now=now)
        except Exception as exc:  # noqa: BLE001
            logger.error("weekly_report tenant=%s action=ERROR %s", tenant, type(exc).__name__)
            out[tenant] = {"action": "ERROR"}
    return out


def _maintenance() -> None:
    store.expire_stale_sending()


async def run_weekly_scheduler() -> None:
    """Every INTERVAL_S. Does nothing while WEEKLY_REPORT_ENABLED is false. Never raises (except cancel)."""
    last_purge = 0.0
    while True:
        try:
            if get_settings().weekly_report_enabled:
                await asyncio.to_thread(run_once, datetime.now(timezone.utc))
                await asyncio.to_thread(_maintenance)
                if time.monotonic() - last_purge > _PURGE_EVERY_S or last_purge == 0.0:
                    await asyncio.to_thread(store.purge_deliveries)
                    last_purge = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("weekly_report pass failed: %s: %s", type(exc).__name__, exc)
        await asyncio.sleep(INTERVAL_S)
