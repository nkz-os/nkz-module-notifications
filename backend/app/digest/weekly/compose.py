"""Pure composition of the weekly report (spec 5, 7.1, 8). No I/O, no HTML."""
from datetime import date, timedelta

HORIZON_DAYS = 13
_GROUPS = ("now", "week", "next", "undated")


def _one_line(s) -> str:
    return " ".join(str(s or "").split())


def _subject_key(subject) -> tuple:
    return (subject.type, subject.id or subject.name)


def _classify(when, week_start: date):
    """-> (group, sort_key) or None when beyond the horizon."""
    if when.type == "today":
        return "now", (1, date.min)
    if when.type == "this_week":
        return "week", (0, date.min)
    if when.type == "undated":
        return "undated", (0, date.min)
    try:
        d = date.fromisoformat(when.date or "")
    except ValueError:
        return "undated", (0, date.min)  # unreadable date: shown, never invented
    if d < week_start:
        return "now", (0, d)
    if d == week_start:
        return "now", (1, d)  # ASSUMPTION: the report goes out on week_start itself, so that day is "today"
    if d <= week_start + timedelta(days=6):
        return "week", (1, d)
    if d <= week_start + timedelta(days=HORIZON_DAYS):
        return "next", (0, d)
    return None


def _dump_link(link):
    return {"kind": link.kind, "params": dict(link.params)} if link is not None else None


def _dump_subject(s):
    return {"type": s.type, "id": s.id, "name": _one_line(s.name)}


def _dump_text(texts):
    return {k: {"title": v.title, "why": v.why} for k, v in texts.items()}


def _clean_plain(plain):
    """Keep only well-formed {lang: {title: str, body: str}} entries; {} when none is usable."""
    if not isinstance(plain, dict):
        return {}
    return {k: {"title": v["title"], "body": v["body"]} for k, v in plain.items()
            if isinstance(v, dict) and isinstance(v.get("title"), str) and isinstance(v.get("body"), str)}


def build(gathered, week_start: date, iso_week: str) -> dict:
    sources = gathered.sources
    failed = [s for s in sources if not s.ok]
    if not sources:
        status = "no_sources"
    elif not any(s.contribution is not None for s in sources) and not gathered.alerts_ok:
        status = "all_failed"
    elif failed or not gathered.alerts_ok:
        status = "partial"
    else:
        status = "complete"

    missing: list[str] = []
    for s in failed:
        label = _one_line(s.label)
        if label and label not in missing:
            missing.append(label)

    seen: set = set()
    ranked = []
    changes, figures = [], []
    for s in sources:
        c = s.contribution
        if c is None:
            continue
        for i, task in enumerate(c.tasks):
            if task.id:  # an empty id identifies nothing: never collapse such tasks
                if (s.key, task.id) in seen:
                    continue
                seen.add((s.key, task.id))
            cls = _classify(task.when, week_start)
            if cls is None:
                continue
            group, sub = cls
            ranked.append(((_GROUPS.index(group), sub), len(ranked), {
                "id": task.id,
                "group": group,
                "subject": _dump_subject(task.subject),
                "kind": task.kind,
                "when": {"type": task.when.type, "date": task.when.date},
                "text": _dump_text(task.text),
                "link": _dump_link(task.link),
                "relatedAlertId": task.relatedAlertId,
                "_key": _subject_key(task.subject),
            }))
        for ch in c.changes:
            changes.append({"subject": _dump_subject(ch.subject), "text": _dump_text(ch.text),
                            "link": _dump_link(ch.link), "_key": _subject_key(ch.subject)})
        for f in c.figures:
            figures.append({"subject": _dump_subject(f.subject),
                            "metrics": [{"key": m.key, "value": m.value, "origin": m.origin} for m in f.metrics],
                            "_key": _subject_key(f.subject)})
    ranked.sort(key=lambda r: (r[0], r[1]))
    tasks = [r[2] for r in ranked]

    related = {t["relatedAlertId"] for t in tasks if t["relatedAlertId"]}
    alerts, extra, alert_ids = [], 0, set()
    for a in gathered.alerts:
        aid = a.get("id")
        if aid and (aid in related or aid in alert_ids):
            continue
        if aid:
            alert_ids.add(aid)
        plain = _clean_plain(a.get("plain"))
        if plain:
            alerts.append({"id": aid, "weather": False, "severity": a.get("severity"), "plain": plain})
        else:
            extra += 1
    for w in gathered.weather_alerts:
        wid = w.get("id")
        if wid and (wid in related or wid in alert_ids):
            continue
        if wid:
            alert_ids.add(wid)
        alerts.append({"id": wid, "weather": True, "severity": w.get("severity"),
                       "description": _one_line(w.get("description")),
                       "parcel_names": [_one_line(n) for n in w.get("parcel_names") or []]})

    touched = {t["_key"] for t in tasks} | {c["_key"] for c in changes}
    unchanged = len({f["_key"] for f in figures} - touched)
    for lst in (tasks, changes, figures):
        for item in lst:
            item.pop("_key")

    return {
        "status": status,
        "iso_week": iso_week,
        "week_start": week_start.isoformat(),
        "farm": _one_line(gathered.tenant_name),
        "missing": missing,
        "alerts_failed": not gathered.alerts_ok,
        "tasks": tasks,
        "changes": changes,
        "alerts": alerts,
        "extra_alerts": extra,
        "figures": figures,
        "unchanged": unchanged,
    }
