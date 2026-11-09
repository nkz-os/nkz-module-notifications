"""Weekly report delivery: email and push per recipient, Zulip once per farm (spec 3, 7.4, 7.5, 8).

No email address is stored or logged: logs and delivery records carry user ids only.
"""
import logging
import time

import requests

from app.config import get_settings
from app.dispatcher import NotificationDispatcher, adapters

from . import render, store
from .prefs_token import preferences_url
from .texts import LANGS

logger = logging.getLogger(__name__)

ROLES = "TenantAdmin,TechnicalConsultant"
ZULIP_TOPIC = "Informe semanal"


def fetch_recipients(tenant_id: str) -> list[dict]:
    s = get_settings()
    r = requests.get(
        f"{s.tenant_user_api_url}/internal/tenants/{tenant_id}/users",
        params={"roles": ROLES},
        headers={"X-Internal-Service-Secret": s.internal_service_secret},
        timeout=60,
    )
    if r.status_code != 200:
        raise RuntimeError(f"recipients API answered HTTP {r.status_code}")
    users = r.json().get("users")
    if not isinstance(users, list):
        raise RuntimeError("recipients API answered an unexpected body")
    return users


def pick_user_lang(locale, default: str) -> str:
    base = str(locale or "").replace("_", "-").split("-")[0].lower()
    if base in LANGS:
        return base
    return default if default in LANGS else "es"


def zulip_stream(tenant_id: str, cfg) -> str | None:
    """Configured stream or the tenant's alerts stream; only the tenant's own alerts/general streams are allowed."""
    stream = (cfg or {}).get("stream") or f"tenant-{tenant_id}-alerts"
    return stream if stream in (f"tenant-{tenant_id}-alerts", f"tenant-{tenant_id}-general") else None


def _tenant_cfg(tenant_id: str) -> dict:
    return NotificationDispatcher(get_settings())._get_channels(tenant_id) or {}


def _cfg(row, key) -> dict:
    v = (row or {}).get(key)
    return v if isinstance(v, dict) else {}


def _scrub(err, email) -> str | None:
    if not err:
        return None
    return str(err).replace(email, "***") if email else str(err)


def deliver(tenant_id: str, report: dict, *, only_user_id: str | None = None, include_zulip: bool = False) -> bool:
    """True when recipients were read and nothing is left unattempted or failed (a failed row is retried later)."""
    s = get_settings()
    week = report["iso_week"]
    try:
        users = fetch_recipients(tenant_id)
        channels = store.get_channels(tenant_id)
        cfg = _tenant_cfg(tenant_id)
    except Exception as e:
        logger.error("weekly_report: cannot prepare delivery tenant=%s week=%s: %s", tenant_id, week, e)
        return False
    if not users:
        # Nobody to send to: never mark the week delivered.
        logger.error("weekly_report: no recipients tenant=%s week=%s", tenant_id, week)
        return False

    ok = True
    default_lang = s.default_lang if s.default_lang in LANGS else "es"
    tenant_lang = pick_user_lang(_cfg(cfg, "push").get("lang"), default_lang)
    app_url = s.public_app_url or None

    email_on = bool(channels.get("email"))
    email_blocked = False
    if email_on and (not s.report_prefs_secret or not s.public_api_url):
        logger.critical(
            "weekly_report: REPORT_PREFS_SECRET or PUBLIC_API_URL missing, email not sent tenant=%s week=%s",
            tenant_id, week)
        email_blocked = True
        ok = False
    base = f"{s.public_api_url.rstrip('/')}{s.api_prefix}" if s.public_api_url else ""

    def record_skip(uid, channel, reason):
        if store.claim_delivery(tenant_id, week, uid, channel):
            store.finish_delivery(tenant_id, week, uid, channel, "skipped", reason)
            logger.info("weekly_report: skipped tenant=%s week=%s user=%s channel=%s reason=%s",
                        tenant_id, week, uid, channel, reason)

    push_users = []
    for u in users:
        uid = u.get("user_id")
        if not uid or (only_user_id is not None and uid != only_user_id):
            continue
        try:
            if not u.get("enabled"):
                record_skip(uid, "email", "disabled")
                record_skip(uid, "push", "disabled")
                continue
            if store.is_opted_out(tenant_id, uid):
                record_skip(uid, "email", "opted_out")
                record_skip(uid, "push", "opted_out")
                continue
            email = u.get("email")
            if email_on and not email:
                record_skip(uid, "email", "no_email")
            elif email_on and not email_blocked:
                ok &= _send_email(s, tenant_id, report, week, uid, email, u.get("locale"), default_lang, base, app_url)
            if store.claim_delivery(tenant_id, week, uid, "push"):
                push_users.append(uid)
        except Exception as e:
            ok = False
            logger.error("weekly_report: user step failed tenant=%s week=%s user=%s: %s", tenant_id, week, uid, e)

    if push_users:
        try:
            ok &= _send_push(s, tenant_id, report, week, push_users, tenant_lang)
        except Exception as e:
            ok = False
            logger.error("weekly_report: push step failed tenant=%s week=%s: %s", tenant_id, week, e)
    if include_zulip and channels.get("zulip") and _cfg(cfg, "zulip").get("enabled"):
        try:
            ok &= _send_zulip(s, tenant_id, report, week, _cfg(cfg, "zulip"), tenant_lang, app_url)
        except Exception as e:
            ok = False
            logger.error("weekly_report: zulip step failed tenant=%s week=%s: %s", tenant_id, week, e)
    return bool(ok)


def _send_email(s, tenant_id, report, week, uid, email, locale, default_lang, base, app_url) -> bool:
    if not store.claim_delivery(tenant_id, week, uid, "email"):
        return True
    try:
        lang = pick_user_lang(locale, default_lang)
        prefs = preferences_url(base, uid, tenant_id, lang, s.report_prefs_secret, int(time.time()))
        mail = render.email(report, lang, prefs, app_url)
        res = adapters.report_email_adapter(
            {"email": email, "subject": mail["subject"], "content_html": mail["content_html"],
             "text": mail["text"], "title": mail["title"], "list_unsubscribe_url": prefs},
            s.email_service_url, s.internal_service_secret)
    except Exception as e:
        res = adapters.DeliveryResult("email", "failed", type(e).__name__)
    status = res.status if res.status in ("sent", "skipped", "unknown") else "failed"
    store.finish_delivery(tenant_id, week, uid, "email", status, _scrub(res.error, email))
    logger.info("weekly_report: email %s tenant=%s week=%s user=%s", status, tenant_id, week, uid)
    return status != "failed"


def _send_push(s, tenant_id, report, week, user_ids, lang) -> bool:
    try:
        p = render.plain(report, lang)
        res = adapters.push_adapter(
            {"tenant_id": tenant_id, "title": p["title"], "summary": p["body"], "channel_id": "silent",
             "user_ids": user_ids,
             "data": {"alertType": "weekly_report", "entityId": week, "parcelId": None,
                      "plain": {"title": p["title"], "body": p["body"]}, "urgency": "silent",
                      "action": {"kind": "open_report", "params": {"reportId": week}}}},
            {"enabled": True}, s.push_service_url, s.internal_service_secret)
    except Exception as e:
        res = adapters.DeliveryResult("push", "failed", type(e).__name__)
    if res.status == "sent" and res.body_status == "no_tokens":
        status, err = "skipped", "no_tokens"  # nobody has a registered device: not "sent to anyone"
    else:
        status = "sent" if res.status == "sent" else "failed"
        err = None if status == "sent" else (f"HTTP {res.code}" if res.code else (res.error or "failed")[:40])
    for uid in user_ids:
        store.finish_delivery(tenant_id, week, uid, "push", status, err)
    logger.info("weekly_report: push %s tenant=%s week=%s users=%d", status, tenant_id, week, len(user_ids))
    return status != "failed"


def _send_zulip(s, tenant_id, report, week, zcfg, lang, app_url) -> bool:
    if not store.claim_delivery(tenant_id, week, "", "zulip"):
        return True
    stream = zulip_stream(tenant_id, zcfg)
    if stream is None:
        store.finish_delivery(tenant_id, week, "", "zulip", "skipped", "stream_outside_tenant")
        logger.error("weekly_report: zulip stream not allowed for tenant, skipped tenant=%s week=%s", tenant_id, week)
        return True
    try:
        res = adapters.zulip_adapter(
            {"summary": render.zulip(report, lang, app_url)},
            {"enabled": True, "stream": stream, "topic": ZULIP_TOPIC},
            s.zulip_service_url, s.internal_service_secret, timeout=adapters.REPORT_TIMEOUT)
    except Exception as e:
        res = adapters.DeliveryResult("zulip", "failed", type(e).__name__)
    status = res.status if res.status in ("sent", "unknown") else "failed"  # unknown: may have posted, never resend
    store.finish_delivery(tenant_id, week, "", "zulip", status, res.error)
    logger.info("weekly_report: zulip %s tenant=%s week=%s", status, tenant_id, week)
    return status != "failed"
