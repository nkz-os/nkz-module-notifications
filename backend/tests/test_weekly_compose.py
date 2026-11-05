"""Weekly report composition: status, horizon, order, dedupe, alerts."""
from datetime import date, timedelta

import pytest

from app.digest.weekly import sources
from app.digest.weekly.compose import build
from app.digest.weekly.models import Contribution

WS = date(2026, 11, 9)


def task(tid, when=None, subj=None, related=None, title="Regar", why="Suelo seco", text=None):
    return {
        "id": tid,
        "subject": subj or {"type": "parcel", "id": "urn:ngsi-ld:AgriParcel:p1", "name": "Olivar Norte"},
        "kind": "irrigate",
        "when": when or {"type": "today", "date": None},
        "text": text if text is not None else {"es": {"title": title, "why": why}, "en": {"title": title + " EN", "why": why + " EN"}},
        "link": {"kind": "open_parcel", "params": {}},
        "relatedAlertId": related,
    }


def contrib(tasks=(), changes=(), figures=(), complete=True):
    return Contribution.parse({"version": 1, "complete": complete, "tasks": list(tasks),
                               "changes": list(changes), "figures": list(figures)})


def src(key="mod-a", ok=True, c=None, label=None):
    return sources.SourceOutcome(key, label or key.upper(), ok, c)


def gathered(srcs, alerts=(), alerts_ok=True, weather=(), name="Finca Acme"):
    return sources.Gathered(sources=list(srcs), alerts=list(alerts), alerts_ok=alerts_ok,
                            weather_alerts=list(weather), tenant_name=name)


def d(offset):
    return {"type": "date", "date": (WS + timedelta(days=offset)).isoformat()}


def test_status_complete():
    r = build(gathered([src(c=contrib([task("1")]))]), WS, "2026-W46")
    assert r["status"] == "complete" and r["missing"] == [] and r["iso_week"] == "2026-W46"
    assert r["week_start"] == "2026-11-09" and r["farm"] == "Finca Acme"


def test_status_partial_source_failed():
    r = build(gathered([src(c=contrib([task("1")])), src("mod-b", ok=False, label="Riego")]), WS, "w")
    assert r["status"] == "partial" and r["missing"] == ["Riego"]


def test_status_partial_complete_false():
    r = build(gathered([src(ok=False, c=contrib([task("1")], complete=False), label="Cultivos")]), WS, "w")
    assert r["status"] == "partial" and r["missing"] == ["Cultivos"] and len(r["tasks"]) == 1


def test_status_partial_alerts_failed():
    r = build(gathered([src(c=contrib([task("1")]))], alerts_ok=False), WS, "w")
    assert r["status"] == "partial" and r["alerts_failed"] is True


def test_status_no_sources():
    assert build(gathered([]), WS, "w")["status"] == "no_sources"
    assert build(gathered([], alerts_ok=False), WS, "w")["status"] == "no_sources"


def test_status_all_failed():
    r = build(gathered([src(ok=False), src("b", ok=False)], alerts_ok=False), WS, "w")
    assert r["status"] == "all_failed"
    # sources failed but Orion answered: still partial, not all_failed
    assert build(gathered([src(ok=False)]), WS, "w")["status"] == "partial"


def test_complete_false_with_data_is_partial_not_all_failed():
    r = build(gathered([src(ok=False, c=contrib([task("1")], complete=False))], alerts_ok=False), WS, "w")
    assert r["status"] == "partial"
    r = build(gathered([src(ok=False, c=contrib([], complete=False)), src("b", ok=False)], alerts_ok=False), WS, "w")
    assert r["status"] == "partial"


def test_task_order():
    ts = [task("undated", {"type": "undated", "date": None}), task("next", d(10)), task("wk-date", d(3)),
          task("wk", {"type": "this_week", "date": None}), task("today", {"type": "today", "date": None}),
          task("overdue", d(-2))]
    r = build(gathered([src(c=contrib(ts))]), WS, "w")
    assert [t["id"] for t in r["tasks"]] == ["overdue", "today", "wk", "wk-date", "next", "undated"]
    assert [t["group"] for t in r["tasks"]] == ["now", "now", "week", "week", "next", "undated"]


def test_horizon_boundaries():
    ts = [task("in", d(13)), task("out", d(14)), task("wk", d(6)), task("nx", d(7))]
    r = build(gathered([src(c=contrib(ts))]), WS, "w")
    groups = {t["id"]: t["group"] for t in r["tasks"]}
    assert groups == {"wk": "week", "nx": "next", "in": "next"}


def test_task_beyond_horizon_dropped():
    r = build(gathered([src(c=contrib([task("far", d(14))]))]), WS, "w")
    assert r["tasks"] == []


def test_duplicate_tasks_same_id_once():
    r = build(gathered([src(c=contrib([task("1"), task("1")]))]), WS, "w")
    assert len(r["tasks"]) == 1


def test_same_id_in_two_modules_kept():
    r = build(gathered([src("a", c=contrib([task("1")])), src("b", c=contrib([task("1")]))]), WS, "w")
    assert len(r["tasks"]) == 2


def test_alert_related_to_task_not_repeated():
    al = [{"id": "urn:a1", "plain": {"es": {"title": "Roya", "body": "Alta"}}, "severity": "high"},
          {"id": "urn:a2", "plain": {"es": {"title": "Helada", "body": "Martes"}}, "severity": "high"}]
    r = build(gathered([src(c=contrib([task("1", related="urn:a1")]))], alerts=al), WS, "w")
    assert [a["id"] for a in r["alerts"]] == ["urn:a2"]


def test_alert_of_dropped_task_still_shown():
    al = [{"id": "urn:a1", "plain": {"es": {"title": "Roya", "body": "Alta"}}}]
    r = build(gathered([src(c=contrib([task("1", d(20), related="urn:a1")]))], alerts=al), WS, "w")
    assert [a["id"] for a in r["alerts"]] == ["urn:a1"]


def test_alert_without_plain_counted():
    al = [{"id": "urn:a1", "alert_type": "soil_dry", "plain": None}, {"id": "urn:a2", "plain": {}}]
    r = build(gathered([src(c=contrib([task("1")]))], alerts=al), WS, "w")
    assert r["alerts"] == [] and r["extra_alerts"] == 2


def test_unchanged_counts_figures_without_task_or_change():
    sub = lambda i: {"type": "parcel", "id": f"urn:p{i}", "name": f"P{i}"}  # noqa: E731
    c = contrib([task("1", subj=sub(1))],
                [{"subject": sub(2), "text": {"es": {"title": "x"}}}],
                [{"subject": sub(i), "metrics": []} for i in (1, 2, 3, 4)])
    r = build(gathered([src(c=c)]), WS, "w")
    assert r["unchanged"] == 2


def test_missing_labels_deduped_and_pure():
    g = gathered([src("a", ok=False, label="Riego"), src("b", ok=False, label="Riego")])
    r = build(g, WS, "w")
    assert r["missing"] == ["Riego"]


def test_alerts_without_id_not_dropped():
    al = [{"plain": {"es": {"title": "A", "body": "a"}}}, {"id": None, "plain": {"es": {"title": "B", "body": "b"}}},
          {"id": "", "plain": None}, {"id": "u1", "plain": {"es": {"title": "C", "body": "c"}}},
          {"id": "u1", "plain": {"es": {"title": "C", "body": "c"}}}]
    r = build(gathered([src(c=contrib([task("1")]))], alerts=al), WS, "w")
    assert len(r["alerts"]) == 3 and r["extra_alerts"] == 1
    w = [{"severity": "severe", "description": "x", "parcel_names": []}, {"severity": "severe", "description": "y", "parcel_names": []}]
    assert len(build(gathered([src(c=contrib([]))], weather=w), WS, "w")["alerts"]) == 2


def test_tasks_with_empty_id_not_collapsed():
    r = build(gathered([src(c=contrib([task("", title="Uno"), task("", title="Dos")]))]), WS, "w")
    assert [t["text"]["es"]["title"] for t in r["tasks"]] == ["Uno", "Dos"]
