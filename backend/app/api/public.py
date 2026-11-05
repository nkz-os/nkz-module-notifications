"""Public (no login) weekly-report preferences page.

Separate router: it must NOT inherit the internal router's auth dependency.
GET never changes state (mail scanners open links); POST applies the change,
including the RFC 8058 one-click POST. Every response, errors included, carries
the same safe headers. Tokens and query strings are never logged.
"""
import html
import logging
import time
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.config import get_settings
from app.digest.weekly import prefs_token, store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public", tags=["public"])

_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'",
}

# ASSUMPTION: eu wording is ours — confirm before shipping
_TEXTS = {
    "es": {
        "title": "Informe semanal",
        "on": "Recibes el informe semanal de la explotación.",
        "off": "No recibes el informe semanal de la explotación.",
        "stop": "Dejar de recibirlo",
        "resume": "Volver a recibirlo",
        "done_off": "Listo: ya no recibirás el informe semanal.",
        "done_on": "Listo: volverás a recibir el informe semanal.",
        "invalid": "Este enlace no es válido o ha caducado.",
    },
    "eu": {
        "title": "Asteko txostena",
        "on": "Ustiapenaren asteko txostena jasotzen duzu.",
        "off": "Ez duzu ustiapenaren asteko txostenik jasotzen.",
        "stop": "Jasotzeari utzi",
        "resume": "Berriz jaso",
        "done_off": "Eginda: ez duzu asteko txostenik jasoko.",
        "done_on": "Eginda: berriz jasoko duzu asteko txostena.",
        "invalid": "Esteka hau ez da baliozkoa edo iraungi egin da.",
    },
    "en": {
        "title": "Weekly report",
        "on": "You receive the weekly farm report.",
        "off": "You do not receive the weekly farm report.",
        "stop": "Stop receiving it",
        "resume": "Receive it again",
        "done_off": "Done: you will no longer receive the weekly report.",
        "done_on": "Done: you will receive the weekly report again.",
        "invalid": "This link is not valid or has expired.",
    },
}


def _lang(raw: str | None) -> str:
    if raw in _TEXTS:
        return raw
    default = get_settings().default_lang
    return default if default in _TEXTS else "en"


def _page(lang: str, message: str, status: int, form: tuple[str, str, str] | None = None) -> HTMLResponse:
    t = _TEXTS[lang]
    body = f"<p>{html.escape(message)}</p>"
    if form:
        action_url, action, label = form
        body += (
            f'<form method="post" action="{html.escape(action_url, quote=True)}">'
            f'<button type="submit" name="action" value="{action}">{html.escape(label)}</button></form>'
        )
    doc = (
        f'<!DOCTYPE html><html lang="{lang}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex">'
        f"<title>{html.escape(t['title'])}</title>"
        "<style>body{font-family:sans-serif;max-width:32rem;margin:3rem auto;padding:0 1rem}"
        "button{font-size:1rem;padding:.6rem 1.2rem}</style></head>"
        f"<body><h1>{html.escape(t['title'])}</h1>{body}</body></html>"
    )
    return HTMLResponse(doc, status_code=status, headers=_HEADERS)


def _check(request: Request) -> tuple[str, str, str, str] | None:
    q = request.query_params
    user, tenant, token = q.get("u", ""), q.get("t", ""), q.get("token", "")
    if not user or not tenant or not token:
        return None
    secret = get_settings().report_prefs_secret
    if not prefs_token.verify(token, user, tenant, secret, int(time.time())):
        return None
    return user, tenant, token, _lang(q.get("lang"))


def _self_url(request: Request, lang: str) -> str:
    q = request.query_params
    return "?" + urlencode({"u": q["u"], "t": q["t"], "lang": lang, "token": q["token"]})


def _state_page(request: Request, user: str, tenant: str, lang: str, message: str | None = None) -> HTMLResponse:
    t = _TEXTS[lang]
    out = store.is_opted_out(tenant, user)
    action, label = ("subscribe", t["resume"]) if out else ("unsubscribe", t["stop"])
    return _page(lang, message or (t["off"] if out else t["on"]), 200, (_self_url(request, lang), action, label))


@router.get("/report-preferences")
async def get_preferences(request: Request):
    ok = _check(request)
    if not ok:
        return _page(_lang(request.query_params.get("lang")), _TEXTS[_lang(request.query_params.get("lang"))]["invalid"], 400)
    user, tenant, _token, lang = ok
    return _state_page(request, user, tenant, lang)


@router.post("/report-preferences")
async def post_preferences(request: Request):
    ok = _check(request)
    if not ok:
        lang = _lang(request.query_params.get("lang"))
        return _page(lang, _TEXTS[lang]["invalid"], 400)
    user, tenant, _token, lang = ok
    t = _TEXTS[lang]
    raw = (await request.body())[:4096]
    form = parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True)
    if form.get("List-Unsubscribe") == ["One-Click"]:
        action = "unsubscribe"
    else:
        action = (form.get("action") or [""])[0]
    if action not in ("unsubscribe", "subscribe"):
        return _page(lang, t["invalid"], 400)
    enabled = action == "subscribe"
    store.set_pref(tenant, user, enabled)
    logger.info("report preference changed enabled=%s", enabled)
    return _state_page(request, user, tenant, lang, t["done_on"] if enabled else t["done_off"])
