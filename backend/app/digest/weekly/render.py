"""Pure rendering of a composed weekly report into email, Zulip and short plain formats (spec 5, 7.5)."""
import html
import math
import re
from datetime import date
from urllib.parse import quote

from .texts import norm_lang, pick_text, t

_GROUP_KEYS = (("now", "grp_now"), ("week", "grp_week"), ("next", "grp_next"), ("undated", "grp_undated"))
_FIG_KEYS = (("rain_mm", "fig_rain"), ("et0_mm", "fig_et0"), ("gdd", "fig_gdd"))
_PLAIN_MAX = 3


def _line(s) -> str:
    return " ".join(str(s or "").split())


def _count(lang, n):
    return t(lang, "count_one") if n == 1 else t(lang, "count_many", n=n)


def subject(report: dict, lang: str) -> str:
    n = len(report["tasks"])
    farm = _line(report.get("farm"))
    sfx = "" if farm else "_nofarm"
    n_alerts = len(report["alerts"]) + report["extra_alerts"]
    if report["status"] == "complete" and n:
        key = "subj_tasks" + sfx
    elif report["status"] == "complete" and n_alerts:
        c = t(lang, "count_alert_one") if n_alerts == 1 else t(lang, "count_alert_many", n=n_alerts)
        return _line(t(lang, "subj_alerts" + sfx, count=c, farm=farm))
    elif report["status"] == "complete":
        key = "subj_none" + sfx
    else:  # never "nothing urgent" unless every source answered completely
        key = ("subj_partial" if n else "subj_partial_none") + sfx
    return _line(t(lang, key, count=_count(lang, n), farm=farm))


def _warn(report, lang):
    if report["status"] == "no_sources":
        return t(lang, "no_modules_line")
    if report["status"] == "complete":
        return ""
    labels = list(report.get("missing") or [])
    if report.get("alerts_failed"):
        labels.append(t(lang, "alerts_label"))
    return t(lang, "partial_line", labels=", ".join(_line(x) for x in labels))


def _url(app_url, subj, link):
    if link is None or subj.get("type") != "parcel" or not subj.get("id"):
        return None
    if not isinstance(app_url, str) or not re.match(r"^https?://", app_url):
        return None
    return f"{app_url.rstrip('/')}/crop-health?parcel={quote(subj['id'], safe='')}"


def _finite(v):
    try:
        return v is not None and not isinstance(v, bool) and math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def _when(task, week_start, lang):
    w = task["when"]
    if w["type"] == "today":
        return t(lang, "when_today")
    if w["type"] == "this_week":
        return t(lang, "when_week")
    if w["type"] == "date":
        try:
            d = date.fromisoformat(w.get("date") or "")
        except ValueError:
            return t(lang, "when_undated")
        if d < week_start:
            return t(lang, "when_overdue", d=d.strftime("%d/%m"))
        if d == week_start:
            return t(lang, "when_today")
        return t(lang, "when_date", d=d.strftime("%d/%m"))
    return t(lang, "when_undated")


def _alert_text(plain, lang):
    """-> (title, body) from the first well-formed entry (lang, es, any), or None."""
    if not isinstance(plain, dict):
        return None
    for code in (lang, "es", *plain.keys()):
        v = plain.get(code)
        if isinstance(v, dict) and isinstance(v.get("title"), str) and isinstance(v.get("body"), str):
            return _line(v["title"]), _line(v["body"])
    return None


def _num(x, lang):
    r = round(float(x), 1)
    s = str(int(r)) if r == int(r) else f"{r:.1f}"
    return s.replace(".", t(lang, "dec"))


def _figure_text(fig, lang):
    parts, origins = [], []
    by_key = {m["key"]: m for m in fig["metrics"] if _finite(m.get("value"))}
    for key, tkey in _FIG_KEYS:
        m = by_key.get(key)
        if m:
            parts.append(t(lang, tkey, x=_num(m["value"], lang)))
            origins.append(m["origin"])
    if not parts:
        return ""
    origin = "origin_sensor" if all(o == "sensor" for o in origins) else "origin_estimated"
    return f"{' · '.join(parts)} ({t(lang, origin)})"


def _blocks(report, lang, app_url):
    lang = norm_lang(lang)
    ws = date.fromisoformat(report["week_start"])
    b = []
    warn = _warn(report, lang)
    if warn:
        b.append(("warn", warn))
    if report["tasks"]:
        b.append(("section", t(lang, "sec_todo")))
        for group, gkey in _GROUP_KEYS:
            items = [x for x in report["tasks"] if x["group"] == group]
            if not items:
                continue
            b.append(("group", t(lang, gkey)))
            for x in items:
                title = _line(pick_text(x["text"], lang, "title")) or t(lang, "no_text")
                why = _line(pick_text(x["text"], lang, "why"))
                b.append(("item", _line(x["subject"]["name"]), title, why, _url(app_url, x["subject"], x["link"]),
                          _when(x, ws, lang)))
    rest = report["unchanged"] if report["status"] == "complete" else 0  # never reassure on partial data
    if report["changes"] or rest:
        b.append(("section", t(lang, "sec_changes")))
        for c in report["changes"]:
            title = _line(pick_text(c["text"], lang, "title")) or t(lang, "no_text")
            b.append(("item", _line(c["subject"]["name"]), title, _line(pick_text(c["text"], lang, "why")),
                      _url(app_url, c["subject"], c["link"]), ""))
        if rest:
            if report["changes"] or report["tasks"]:
                key = "rest_one" if rest == 1 else "rest_many"
            else:
                key = "all_one" if rest == 1 else "all_many"
            b.append(("note", t(lang, key, n=rest)))
    if report["alerts"] or report["extra_alerts"]:
        b.append(("section", t(lang, "sec_alerts")))
        for a in report["alerts"]:
            if a["weather"]:
                desc = a.get("description") if lang == "es" else ""
                sev = a.get("severity")
                if desc:
                    text = desc + t(lang, "forecast_suffix")
                elif sev in ("severe", "moderate"):
                    text = t(lang, "weather_sev", sev=t(lang, "sev_" + sev))
                else:
                    text = t(lang, "weather_generic")
                names = [_line(n) for n in a.get("parcel_names") or [] if _line(n)]
                if names:
                    shown = ", ".join(names[:3])
                    if len(names) > 3:
                        shown += " " + t(lang, "more", n=len(names) - 3)
                    text += f": {shown}"
                b.append(("item", "", text, "", None, ""))
            else:
                tb = _alert_text(a.get("plain"), lang)
                title, body = tb if tb else ("", "")
                b.append(("item", "", title or t(lang, "no_text"), body, None, ""))
        n = report["extra_alerts"]
        if n:
            b.append(("note", t(lang, "extra_alerts_one" if n == 1 else "extra_alerts_many", n=n)))
    fig_items = []
    for f in report["figures"]:
        text = _figure_text(f, lang)
        if text:
            fig_items.append(("item", _line(f["subject"]["name"]), text, "", None, ""))
    if fig_items:
        b.append(("section", t(lang, "sec_figures")))
        b.extend(fig_items)
    return b


def _head(name, title, when=""):
    head = f"{name}: {title}" if name else title
    return f"{head} — {when}" if when else head


def _text(blocks, prefs_url=None, lang="es"):
    out = []
    for blk in blocks:
        kind = blk[0]
        if kind == "warn":
            out += [blk[1], ""]
        elif kind == "section":
            out += ["", blk[1]]
        elif kind == "group":
            out.append(blk[1])
        elif kind == "item":
            _, name, title, why, url, when = blk
            out.append(f"• {_head(name, title, when)}")
            if why:
                out.append(f"  {why}")
            if url:
                out.append(f"  {url}")
        else:
            out.append(blk[1])
    if _safe_url(prefs_url):
        out += ["", f"{t(lang, 'unsubscribe')}: {prefs_url}"]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out).strip()) + "\n"


def _safe_url(u):
    return isinstance(u, str) and bool(re.match(r"^https?://", u))


def _html(blocks, prefs_url, lang):
    e = html.escape
    out = ['<div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:1.45;color:#1f2933;max-width:640px">']
    in_list = False

    def close():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for blk in blocks:
        kind = blk[0]
        if kind == "warn":
            close()
            out.append(f'<p style="background:#fff4e5;border-left:4px solid #d97706;padding:8px 12px;margin:0 0 16px"><strong>{e(blk[1])}</strong></p>')
        elif kind == "section":
            close()
            out.append(f'<h2 style="font-size:14px;letter-spacing:.04em;margin:20px 0 6px;color:#374151">{e(blk[1])}</h2>')
        elif kind == "group":
            close()
            out.append(f'<p style="margin:8px 0 2px;font-weight:bold">{e(blk[1])}</p>')
        elif kind == "item":
            if not in_list:
                out.append('<ul style="margin:0 0 8px;padding-left:20px">')
                in_list = True
            _, name, title, why, url, when = blk
            label = e(_head(name, title, when))
            if url:
                label = f'<a href="{e(url, quote=True)}" style="color:#0b5cad">{label}</a>'
            why_html = f'<br><span style="color:#4b5563">{e(why)}</span>' if why else ""
            out.append(f"<li>{label}{why_html}</li>")
        else:
            close()
            out.append(f'<p style="margin:4px 0">{e(blk[1])}</p>')
    close()
    if _safe_url(prefs_url):
        out.append(f'<p style="margin:24px 0 0;font-size:12px"><a href="{e(prefs_url, quote=True)}" style="color:#6b7280">{e(t(lang, "unsubscribe"))}</a></p>')
    out.append("</div>")
    return "\n".join(out)


_MD = re.compile(r"([\\`*_\[\]#<>])")


def _md(s):
    # Escapes Markdown and Zulip mention syntax (@**all** would notify the whole stream).
    return _MD.sub(r"\\\1", s).replace("@", "@\u200b")


def email(report: dict, lang: str, prefs_url, app_url) -> dict:
    lang = norm_lang(lang)
    blocks = _blocks(report, lang, app_url)
    subj = subject(report, lang)
    return {"subject": subj, "title": subj, "text": _text(blocks, prefs_url, lang),
            "content_html": _html(blocks, prefs_url, lang)}


def zulip(report: dict, lang: str, app_url=None) -> str:
    lang = norm_lang(lang)
    out = [f"**{_md(subject(report, lang))}**", ""]
    for blk in _blocks(report, lang, app_url):
        kind = blk[0]
        if kind == "warn":
            out += [f"**{_md(blk[1])}**", ""]
        elif kind == "section":
            out += ["", f"**{_md(blk[1])}**"]
        elif kind == "group":
            out.append(f"*{_md(blk[1])}*")
        elif kind == "item":
            _, name, title, why, url, when = blk
            head = _md(_head(name, title, when))
            if url:
                head = f"[{head}]({url.replace(')', '%29')})"
            out.append(f"- {head}")
            if why:
                out.append(f"  {_md(why)}")
        else:
            out.append(_md(blk[1]))
    return "\n".join(out).strip() + "\n"


def plain(report: dict, lang: str) -> dict:
    lang = norm_lang(lang)
    tasks = report["tasks"]
    lines = []
    for x in tasks[:_PLAIN_MAX]:
        title = _line(pick_text(x["text"], lang, "title")) or t(lang, "no_text")
        lines.append(_head(_line(x["subject"]["name"]), title,
                           _when(x, date.fromisoformat(report["week_start"]), lang)))
    if len(tasks) > _PLAIN_MAX:
        lines.append(t(lang, "more", n=len(tasks) - _PLAIN_MAX))
    if not tasks:
        lines.append(_warn(report, lang) or t(lang, "plain_empty"))
    return {"title": subject(report, lang), "body": "\n".join(lines)}
