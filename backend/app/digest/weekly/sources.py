"""Weekly report source gathering (spec 7.1/7.2).

Every failure surfaces as a failed source or alerts_ok=False; nothing is swallowed into empty data.
"""
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from urllib.parse import urlparse

import requests
from nkz_platform_sdk import SyncOrionClient

from app.config import get_settings
from app.db import get_conn
from app.dispatcher.router import alert_to_info

from .models import Contribution

logger = logging.getLogger(__name__)

MODULE_TIMEOUT_S = 60
_PAGE = 100
_MAX_PAGES = 50
_WEATHER_CAP = 5
_WEATHER_SEVERITY_RANK = {"severe": 0, "moderate": 1}
# WeatherAlert entities are geographic and live in the cross-tenant scope (same env as weather-api).
_SHARED_TENANT = os.getenv("SHARED_GEO_TENANT", "shared")
_CLUSTER_HOST = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", re.IGNORECASE)


@dataclass
class SourceOutcome:
    key: str
    label: str
    ok: bool
    contribution: Contribution | None


@dataclass
class Gathered:
    sources: list[SourceOutcome]
    alerts: list[dict]
    alerts_ok: bool
    weather_alerts: list[dict]
    tenant_name: str


def _unwrap(value):
    if isinstance(value, dict):
        return value.get("value", value.get("object"))
    return value


def list_sources(tenant_id: str) -> list[dict]:
    """Report sources of modules installed and enabled for the tenant. Raises on DB failure."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT s.module_id, s.display_name, s.weekly_report_url
                FROM public.module_report_sources s
                JOIN public.module_installations i ON i.module_id = s.module_id
                WHERE i.tenant_id = %s AND i.is_enabled
                ORDER BY s.module_id
                """,
                (tenant_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        url = (r.get("weekly_report_url") or "").strip()
        if url:
            out.append({"module_id": r["module_id"], "display_name": r.get("display_name") or r["module_id"],
                        "weekly_report_url": url})
    return out


def _tenant_name(tenant_id: str) -> str:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT tenant_name FROM public.module_tenant_plan WHERE tenant_id = %s LIMIT 1",
                        (tenant_id,))
            row = cur.fetchone()
    finally:
        conn.close()
    name = (row or {}).get("tenant_name")
    if not name:
        logger.warning("weekly report: no tenant_name for %s; leaving it empty", tenant_id)
    return name or ""  # never an id: the renderer handles the empty name


def _in_cluster(url: str) -> bool:
    """Only plain in-cluster service names (no dots): the secret must never leave the cluster."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(host) and bool(_CLUSTER_HOST.match(host))


def _call_module(src: dict, tenant_id: str, week_start: date) -> SourceOutcome:
    key, label, url = src["module_id"], src["display_name"], src["weekly_report_url"]
    failed = SourceOutcome(key, label, False, None)
    try:
        resp = requests.get(
            url,
            params={"tenant_id": tenant_id, "week_start": week_start.isoformat()
                    if hasattr(week_start, "isoformat") else str(week_start)},
            headers={"X-Internal-Service-Secret": get_settings().internal_service_secret},
            timeout=MODULE_TIMEOUT_S,
            allow_redirects=False,
        )
        if resp.status_code != 200:
            logger.warning("weekly report source %s tenant=%s: HTTP %s", key, tenant_id, resp.status_code)
            return failed
        contribution = Contribution.parse(resp.json())
    except Exception as exc:  # noqa: BLE001 - any failure is a failed source, visibly
        logger.warning("weekly report source %s tenant=%s failed: %s: %s", key, tenant_id,
                       type(exc).__name__, exc)
        return failed
    return SourceOutcome(key, label, contribution.complete, contribution)


def _query_all(orion, entity_type: str, q: str | None = None) -> list[dict]:
    out: list[dict] = []
    for page_no in range(_MAX_PAGES):
        page = orion.query_entities(type=entity_type, q=q, limit=_PAGE, offset=page_no * _PAGE,
                                    options="keyValues") or []
        out.extend(page)
        if len(page) < _PAGE:
            return out
    raise RuntimeError(f"too many {entity_type} entities (> {_MAX_PAGES * _PAGE})")


def _client(tenant: str):
    s = get_settings()
    return SyncOrionClient(tenant, base_url=s.orion_ld_url, context_url=s.context_url)


def _fetch_alerts(tenant_id: str) -> tuple[list[dict], bool]:
    try:
        with _client(tenant_id) as orion:
            entities = _query_all(orion, "Alert")
    except Exception as exc:  # noqa: BLE001
        logger.warning("weekly report: Alert read failed tenant=%s: %s", tenant_id, exc)
        return [], False
    out = []
    for e in entities:
        info = alert_to_info(e)  # None unless active
        if info is None or info["alert_type"].startswith("work_"):
            continue
        out.append(info)
    return out, True


def _centroid(entity: dict) -> tuple[float, float] | None:
    """(lon, lat) centroid of an AgriParcel `location` (normalized or keyValues); None if unusable."""
    loc = (entity or {}).get("location")
    value = loc.get("value", loc) if isinstance(loc, dict) else None
    if not isinstance(value, dict):
        return None
    gtype, coords = value.get("type"), value.get("coordinates")
    try:
        if gtype == "Point" and isinstance(coords, list) and len(coords) >= 2:
            return (float(coords[0]), float(coords[1]))
        if gtype in ("Polygon", "MultiPolygon") and isinstance(coords, list) and coords:
            ring = coords[0] if gtype == "Polygon" else coords[0][0]
            pts = [p for p in ring if isinstance(p, list) and len(p) >= 2]
            if len(pts) > 1 and pts[0][:2] == pts[-1][:2]:
                pts = pts[:-1]  # closing vertex would skew the mean
            if pts:
                return (sum(float(p[0]) for p in pts) / len(pts), sum(float(p[1]) for p in pts) / len(pts))
    except (TypeError, ValueError, IndexError):
        return None
    return None


def _geo_query_all(orion, lon: float, lat: float, q: str) -> list[dict]:
    """Paged WeatherAlert geo-query (the SDK's query_entities has no geo parameters)."""
    out: list[dict] = []
    for page_no in range(_MAX_PAGES):
        resp = orion._session.get(
            orion._url("/ngsi-ld/v1/entities"),
            params={
                "type": "WeatherAlert",
                "georel": "intersects",
                "geometry": "Point",
                "coordinates": f"[{lon},{lat}]",
                "geoproperty": "location",
                "q": q,
                "options": "keyValues",
                "limit": _PAGE,
                "offset": page_no * _PAGE,
            },
            headers=orion._headers("application/json"),
            timeout=orion.timeout,
        )
        resp.raise_for_status()
        page = resp.json() or []
        out.extend(page)
        if len(page) < _PAGE:
            return out
    raise RuntimeError(f"too many WeatherAlert entities (> {_MAX_PAGES * _PAGE})")


def _fetch_weather_alerts(tenant_id: str, now: datetime | None = None) -> tuple[list[dict], bool]:
    """Severe/moderate WeatherAlerts that intersect this tenant's parcels (max 5, severe first)."""
    now = now or datetime.now(timezone.utc)
    now_iso = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    q = f'validTo>"{now_iso}"'
    try:
        with _client(tenant_id) as orion:
            parcels = _query_all(orion, "AgriParcel")
        points = []
        for p in parcels:
            c = _centroid(p)
            if c is None:
                logger.warning("weekly report: parcel %s has no usable geometry, skipped for weather alerts",
                               (p or {}).get("id"))
                continue
            points.append((str(_unwrap((p or {}).get("name")) or "").strip(), c))
        if not points:
            return [], True
        found: dict[str, dict] = {}
        with _client(_SHARED_TENANT) as orion:
            for name, (lon, lat) in points:
                for e in _geo_query_all(orion, lon, lat, q):
                    if not isinstance(e, dict) or not e.get("id"):
                        continue
                    entry = found.setdefault(e["id"], {"entity": e, "parcel_names": []})
                    if name and name not in entry["parcel_names"]:
                        entry["parcel_names"].append(name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("weekly report: WeatherAlert read failed tenant=%s: %s", tenant_id, exc)
        return [], False
    out = []
    for entry in found.values():
        e = entry["entity"]
        severity = str(_unwrap(e.get("severity")) or "").lower()
        valid_to = _unwrap(e.get("validTo"))
        if severity not in _WEATHER_SEVERITY_RANK or not isinstance(valid_to, str) or valid_to <= now_iso:
            continue
        out.append({
            "id": e["id"],
            "severity": severity,
            "description": str(_unwrap(e.get("description")) or "").strip(),
            "validFrom": _unwrap(e.get("validFrom")),
            "validTo": valid_to,
            "parcel_names": entry["parcel_names"],
        })
    out.sort(key=lambda a: _WEATHER_SEVERITY_RANK[a["severity"]])
    return out[:_WEATHER_CAP], True


def parcel_timezones(tenant_id: str) -> list[str]:
    """IANA timeZone of each parcel that declares one. Raises if Orion fails."""
    with _client(tenant_id) as orion:
        parcels = _query_all(orion, "AgriParcel")
    zones = []
    for p in parcels:
        tz = _unwrap((p or {}).get("timeZone"))
        if isinstance(tz, str) and tz:
            zones.append(tz)
    return zones


def gather(tenant_id: str, week_start: date) -> Gathered:
    outcomes = []
    for src in list_sources(tenant_id):
        if not _in_cluster(src["weekly_report_url"]):
            logger.error("weekly report: source %s not called, URL is not an in-cluster service name",
                         src["module_id"])
            outcomes.append(SourceOutcome(src["module_id"], src["display_name"], False, None))
            continue
        outcomes.append(_call_module(src, tenant_id, week_start))
    alerts, alerts_ok = _fetch_alerts(tenant_id)
    weather, weather_ok = _fetch_weather_alerts(tenant_id)
    return Gathered(
        sources=outcomes,
        alerts=alerts,
        alerts_ok=alerts_ok and weather_ok,
        weather_alerts=weather,
        tenant_name=_tenant_name(tenant_id),
    )
