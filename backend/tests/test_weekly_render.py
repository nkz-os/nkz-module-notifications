"""Weekly report rendering: subject, no false reassurance, escaping, standalone lines, links."""
from datetime import date

import pytest

from app.digest.weekly import render
from app.digest.weekly.compose import build
from tests.test_weekly_compose import contrib, d, gathered, src, task

WS = date(2026, 11, 9)
APP = "https://app.example.test"
PREFS = "https://app.example.test/prefs?t=abc"
LANGS = ("es", "eu", "en")


def rep(tasks=(), srcs=None, **kw):
    srcs = srcs if srcs is not None else [src(c=contrib(tasks, kw.pop("changes", ()), kw.pop("figures", ())))]
    return build(gathered(srcs, **kw), WS, "2026-W46")


def test_subject_es_forms():
    assert render.subject(rep([task("1"), task("2"), task("3")]), "es") == "Esta semana: 3 tareas en Finca Acme"
    assert render.subject(rep([task("1")]), "es") == "Esta semana: 1 tarea en Finca Acme"
    assert render.subject(rep([]), "es") == "Esta semana no hay nada urgente en Finca Acme"


def test_subject_partial_es():
    s = [src(c=contrib([task("1"), task("2")])), src("b", ok=False)]
    assert render.subject(rep(srcs=s), "es") == "Informe incompleto: 2 tareas en Finca Acme"
    assert render.subject(rep(srcs=[src(ok=False)]), "es") == "Informe incompleto para Finca Acme"


@pytest.mark.parametrize("lang", LANGS)
def test_empty_farm_omits_it(lang):
    r = rep([task("1"), task("2"), task("3")], name="")
    s = render.subject(r, lang)
    assert "3" in s and "urn" not in s and "None" not in s and "{" not in s
    assert render.subject(rep([task("1"), task("2"), task("3")], name=""), "es") == "Esta semana: 3 tareas"
    assert "  " not in render.subject(rep([], name=""), lang)


@pytest.mark.parametrize("lang", LANGS)
def test_never_nothing_urgent_when_partial(lang):
    none_texts = {"es": "nada urgente", "en": "nothing urgent", "eu": "ez dago ezer premiazkorik"}
    for r in (rep(srcs=[src(c=contrib([])), src("b", ok=False)]),
              rep(srcs=[src(c=contrib([]), ok=False)]),
              rep(srcs=[src(c=contrib([]))], alerts_ok=False),
              rep(srcs=[])):
        e = render.email(r, lang, PREFS, APP)
        blob = (e["subject"] + e["text"] + render.zulip(r, lang) + str(render.plain(r, lang))).lower()
        assert none_texts[lang] not in blob


def test_complete_empty_says_nothing_urgent_only_here():
    assert "nada urgente" in render.subject(rep([]), "es")


def test_partial_first_line_names_sources():
    r = rep(srcs=[src(c=contrib([task("1")])), src("b", ok=False, label="Riego")])
    text = render.email(r, "es", PREFS, APP)["text"]
    assert text.splitlines()[0] == ("Falta parte de los datos: Riego. "
                                    "No se puede asegurar que no haya nada más que hacer.")


def test_partial_alerts_only_names_alerts():
    r = rep([task("1")], alerts_ok=False)
    assert "avisos activos" in render.email(r, "es", PREFS, APP)["text"].splitlines()[0]


def test_no_reassurance_line_when_partial():
    sub = {"type": "parcel", "id": "urn:p9", "name": "Quieta"}
    f = [{"subject": sub, "metrics": []}]
    ok = render.email(rep([task("1")], figures=f), "es", PREFS, APP)["text"]
    bad = render.email(rep(srcs=[src(c=contrib([task("1")], figures=f)), src("b", ok=False)]), "es", PREFS, APP)["text"]
    assert "sin novedad" in ok and "sin novedad" not in bad


def test_sections_and_groups_es():
    ts = [task("a", d(-1)), task("b", d(3)), task("c", d(9)), task("e", {"type": "undated", "date": None})]
    text = render.email(rep(ts), "es", PREFS, APP)["text"]
    for h in ("QUÉ HACER", "Hoy o vencido", "Esta semana", "Próxima semana", "Sin fecha"):
        assert h in text


def test_alert_without_plain_counted_not_printed():
    al = [{"id": "urn:a", "alert_type": "soil_dry_stress", "plain": None}]
    r = rep([task("1")], alerts=al)
    e = render.email(r, "es", PREFS, APP)
    assert "soil_dry_stress" not in e["text"] + e["content_html"]
    assert "1 aviso más en la app." in e["text"]


def test_weather_alert_copy():
    w = [{"id": "w", "severity": "severe", "description": "Riesgo de helada el martes", "parcel_names": []}]
    r = rep([task("1")], weather=w)
    assert "Riesgo de helada el martes (previsión)" in render.email(r, "es", PREFS, APP)["text"]
    en = render.email(r, "en", PREFS, APP)["text"]
    assert "Severe weather alert (forecast)" in en and "helada" not in en


def test_machine_subject_renders_like_parcel():
    t = task("1", subj={"type": "machine", "id": "urn:m", "name": "Tractor Uno"}, title="Revisar aceite",
             why="Pasadas 200 horas")
    t["link"] = None
    text = render.email(rep([t]), "es", PREFS, APP)["text"]
    assert "• Tractor Uno: Revisar aceite" in text and "Pasadas 200 horas" in text and "http://" not in text.split("•")[1]


def test_farm_subject_without_name_has_no_leading_colon():
    t = task("1", subj={"type": "farm", "id": "", "name": ""}, title="Renovar seguro", why="Vence pronto")
    t["link"] = None
    text = render.email(rep([t]), "es", None, APP)["text"]
    assert "• Renovar seguro" in text and "• : " not in text and ": Renovar" not in text


def test_no_codes_in_output():
    al = [{"id": "urn:ngsi-ld:Alert:1", "alert_type": "soil_dry", "plain": None}]
    text = render.email(rep([task("1")], alerts=al), "es", None, None)["text"]
    assert "urn:" not in text and "_" not in text


def test_html_escapes_all_module_text():
    t = task("1", subj={"type": "parcel", "id": "urn:p", "name": "<script>n</script>"},
             title="<script>t</script>", why="<img onerror=x>")
    srcs = [src(c=contrib([t]), label="<b>Mod</b>"), src("b", ok=False, label="<i>Fail</i>")]
    r = rep(srcs=srcs, name="<u>Finca</u>")
    e = render.email(r, "es", PREFS, APP)
    for raw in ("<script>", "<img", "<b>", "<i>", "<u>"):
        assert raw not in e["content_html"]
    assert "&lt;script&gt;" in e["content_html"]


def test_subject_strips_newlines():
    r = rep([task("1")], name="A\r\nB")
    for lang in LANGS:
        e = render.email(r, lang, PREFS, APP)
        assert "\r" not in e["subject"] and "\n" not in e["subject"] and "A B" in e["subject"]


def test_mixed_origin_says_estimated():
    sub = {"type": "parcel", "id": "urn:p", "name": "Olivar Norte"}
    f = [{"subject": sub, "metrics": [{"key": "rain_mm", "value": 0, "origin": "sensor"},
                                       {"key": "et0_mm", "value": 18.0, "origin": "estimated"},
                                       {"key": "gdd", "value": 45.3, "origin": "estimated"}]}]
    text = render.email(rep([], figures=f), "es", PREFS, APP)["text"]
    assert "Olivar Norte: lluvia 0 mm · evapotranspiración 18 mm · calor acumulado 45,3 °C·día (estimado)" in text
    f[0]["metrics"] = [{"key": "rain_mm", "value": 2.5, "origin": "sensor"}]
    assert "lluvia 2,5 mm (medido)" in render.email(rep([], figures=f), "es", PREFS, APP)["text"]


def test_figure_with_missing_value_omits_it():
    f = [{"subject": {"type": "parcel", "id": "urn:p", "name": "P"},
          "metrics": [{"key": "rain_mm", "value": None, "origin": "estimated"},
                      {"key": "et0_mm", "value": 3, "origin": "estimated"}]}]
    text = render.email(rep([], figures=f), "es", PREFS, APP)["text"]
    assert "lluvia" not in text and "evapotranspiración 3 mm" in text


def test_each_line_standalone():
    ts = [task("1", title="Regar esta semana", why="El suelo empieza a secarse"),
          task("2", subj={"type": "parcel", "id": "urn:p2", "name": "La Vega"}, title="Cosecha prevista",
               why="Hacia el 14 de noviembre")]
    text = render.email(rep(ts), "es", None, None)["text"]
    items = text.split("• ")[1:]
    assert len(items) == 2
    for item, name, why in zip(items, ("Olivar Norte", "La Vega"), ("El suelo empieza", "Hacia el 14")):
        assert name in item.splitlines()[0] and why in item


def test_links():
    r = rep([task("1")])
    text = render.email(r, "es", PREFS, APP)["text"]
    assert f"{APP}/crop-health?parcel=urn%3Angsi-ld%3AAgriParcel%3Ap1" in text
    assert "/viewer?" not in text
    for app in (None, "", "javascript:alert(1)"):
        e = render.email(r, "es", PREFS, app)
        assert "crop-health" not in e["text"] + e["content_html"]
    assert 'href="https://app.example.test/crop-health?parcel=' in render.email(r, "es", PREFS, APP)["content_html"]


def test_plain_summary_cap():
    r = rep([task(str(i), title=f"Tarea {i}") for i in range(5)])
    p = render.plain(r, "es")
    assert p["title"] == render.subject(r, "es")
    lines = p["body"].splitlines()
    assert len(lines) == 4 and lines[-1] == "y 2 más" and lines[0] == "Olivar Norte: Tarea 0 — hoy"
    assert len(render.plain(rep([task("1")]), "es")["body"].splitlines()) == 1


def test_plain_partial_without_tasks_has_warning():
    p = render.plain(rep(srcs=[src(ok=False, label="Riego")]), "es")
    assert "Riego" in p["body"] and "nada urgente" not in p["body"]


def test_lang_fallback():
    t = task("1", text={"es": {"title": "Regar", "why": "Seco"}, "en": {"title": "Water", "why": "Dry"}})
    r = rep([t])
    assert "Regar" in render.email(r, "eu", PREFS, APP)["text"]  # eu missing -> default es
    t = task("1", text={"en": {"title": "Water", "why": "Dry"}})
    assert "Water" in render.email(rep([t]), "eu", PREFS, APP)["text"]  # no es -> any
    assert "Water" in render.email(rep([t]), "ca", PREFS, APP)["text"]  # unknown locale
    t = task("1", text={})
    assert "Tarea pendiente" in render.email(rep([t]), "es", PREFS, APP)["text"]


def test_unsubscribe_link():
    e = render.email(rep([task("1")]), "es", PREFS, APP)
    assert "Dejar de recibir este informe" in e["text"] and PREFS in e["text"]
    assert PREFS in e["content_html"]
    assert "Dejar de recibir" not in render.email(rep([task("1")]), "es", None, APP)["text"]
    assert "javascript" not in render.email(rep([task("1")]), "es", "javascript:x", APP)["content_html"]


def test_zulip_defuses_mentions_and_markdown():
    t = task("1", subj={"type": "parcel", "id": "urn:p", "name": "@**all** [x](http://e)"}, title="*bold*")
    z = render.zulip(rep([t]), "es")
    assert "@**all**" not in z and "[x](http" not in z


def test_zulip_has_link_and_sections():
    z = render.zulip(rep([task("1")]), "es", APP)
    assert "QUÉ HACER" in z and f"({APP}/crop-health?parcel=" in z


@pytest.mark.parametrize("lang", LANGS)
def test_all_langs_render_every_status(lang):
    al = [{"id": "x", "plain": None}]
    w = [{"id": "w", "severity": "severe", "description": "d", "parcel_names": ["P"]}]
    for r in (rep([task("1", d(-1))], alerts=al, weather=w), rep(srcs=[]), rep(srcs=[src(ok=False)], alerts_ok=False)):
        e = render.email(r, lang, PREFS, APP)
        assert e["subject"] and e["text"] and e["content_html"] and e["title"] == e["subject"]
        assert "{" not in e["text"] and "KeyError" not in e["text"]


ALERT_PLAIN = {"id": "urn:a", "severity": "high", "plain": {"es": {"title": "Helada", "body": "Martes"}}}
WEATHER = {"id": "w", "severity": "severe", "description": "", "parcel_names": []}


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("kw", [{"alerts": [ALERT_PLAIN]}, {"weather": [WEATHER]},
                                {"alerts": [{"id": "x", "plain": None}]}])
def test_zero_tasks_with_alerts_never_nothing_urgent(lang, kw):
    none_texts = {"es": "nada urgente", "en": "nothing urgent", "eu": "ez dago ezer premiazkorik"}
    r = rep([], **kw)
    e = render.email(r, lang, PREFS, APP)
    blob = (e["subject"] + e["text"] + render.zulip(r, lang) + str(render.plain(r, lang))).lower()
    assert none_texts[lang] not in blob and "{" not in e["subject"]


def test_subject_alerts_forms():
    assert render.subject(rep([], alerts=[ALERT_PLAIN]), "es") == "Esta semana: 1 aviso en Finca Acme"
    assert render.subject(rep([], alerts=[ALERT_PLAIN], weather=[WEATHER]), "es") == "Esta semana: 2 avisos en Finca Acme"
    assert render.subject(rep([], alerts=[ALERT_PLAIN], name=""), "es") == "Esta semana: 1 aviso"
    assert render.subject(rep([], alerts=[ALERT_PLAIN]), "en") == "This week: 1 alert at Finca Acme"
    assert render.subject(rep([], alerts=[ALERT_PLAIN], weather=[WEATHER], name=""), "en") == "This week: 2 alerts"
    assert "abisu" in render.subject(rep([], alerts=[ALERT_PLAIN]), "eu")
    assert render.subject(rep([task("1")], alerts=[ALERT_PLAIN]), "es") == "Esta semana: 1 tarea en Finca Acme"


@pytest.mark.parametrize("lang,word", [("es", "grave"), ("en", "Severe"), ("eu", "larria")])
def test_weather_severity_in_plain_words(lang, word):
    text = render.email(rep([task("1")], weather=[WEATHER]), lang, PREFS, APP)["text"]
    assert word in text
    assert "severe" not in text.replace("Severe", "")


def test_weather_severity_es_exact_and_moderate():
    mod = dict(WEATHER, severity="moderate")
    assert "Aviso meteorológico grave (previsión)" in render.email(rep([task("1")], weather=[WEATHER]), "es", PREFS, APP)["text"]
    assert "Moderate weather alert (forecast)" in render.email(rep([task("1")], weather=[mod]), "en", PREFS, APP)["text"]


@pytest.mark.parametrize("when,es,en,eu", [
    ({"type": "today", "date": None}, "— hoy", "— today", "— gaur"),
    (d(-3), "— vencida (06/11)", "— overdue (06/11)", "— atzeratuta (06/11)"),
    ({"type": "this_week", "date": None}, "— esta semana", "— this week", "— aste honetan"),
    (d(5), "— para el 14/11", "— for 14/11", "— 14/11rako"),
    (d(10), "— para el 19/11", "— for 19/11", "— 19/11rako"),
    ({"type": "undated", "date": None}, "— sin fecha", "— no date", "— datarik gabe"),
])
def test_each_line_carries_when(when, es, en, eu):
    r = rep([task("1", when)])
    for lang, want in (("es", es), ("en", en), ("eu", eu)):
        e = render.email(r, lang, PREFS, APP)
        item = [ln for ln in e["text"].splitlines() if ln.startswith("• ")][0]
        assert want in item
        assert want in html_unescape(e["content_html"]) and want in render.zulip(r, lang, APP)
    assert want in render.plain(r, "eu")["body"]
    assert es in render.plain(r, "es")["body"]


def html_unescape(s):
    import html
    return html.unescape(s)


def test_rest_says_other_when_tasks_exist():
    sub = lambda i: {"type": "parcel", "id": f"urn:p{i}", "name": f"P{i}"}  # noqa: E731
    f = [{"subject": sub(i), "metrics": []} for i in (2, 3, 4)]
    text = render.email(rep([task("1", subj=sub(1))], figures=f), "es", PREFS, APP)["text"]
    assert "Las otras 3 parcelas, sin novedad." in text
    text = render.email(rep([], figures=f), "es", PREFS, APP)["text"]
    assert "Las 3 parcelas, sin novedad." in text and "otras" not in text


def test_non_finite_figures_skipped():
    f = [{"subject": {"type": "parcel", "id": "urn:p", "name": "P"},
          "metrics": [{"key": "rain_mm", "value": float("nan"), "origin": "estimated"},
                      {"key": "et0_mm", "value": float("inf"), "origin": "estimated"},
                      {"key": "gdd", "value": 10, "origin": "estimated"}]}]
    text = render.email(rep([], figures=f), "es", PREFS, APP)["text"]
    assert "lluvia" not in text and "evapotranspiración" not in text and "calor acumulado 10" in text


def test_malformed_plain_counted_not_crashing():
    al = [{"id": "a1", "plain": {"es": {"title": "solo titulo"}}}, {"id": "a2", "plain": {"es": "texto"}},
          {"id": "a3", "plain": {"es": None}}]
    r = rep([task("1")], alerts=al)
    assert r["extra_alerts"] == 3 and r["alerts"] == []
    # stored/legacy report with a malformed entry still renders
    r["alerts"] = [{"id": "x", "weather": False, "severity": "high", "plain": {"es": {"title": "t"}, "en": "z"}}]
    assert "Tarea pendiente" in render.email(r, "es", PREFS, APP)["text"]
    r["alerts"] = [{"id": "x", "weather": False, "severity": "high", "plain": {"es": "z", "en": {"title": "T", "body": "B"}}}]
    assert "T" in render.email(r, "es", PREFS, APP)["text"]


def test_zulip_escapes_only_what_matters():
    t = task("1", subj={"type": "parcel", "id": "urn:p", "name": "@all @**all** _x_"}, title="a: b (c) - d.")
    z = render.zulip(rep([t, task("2")]), "es")
    assert "\\:" not in z and "\\(" not in z and "\\-" not in z and "\\." not in z
    assert "Esta semana: 2 tareas" in z.splitlines()[0] and "\\" not in z.splitlines()[0]
    assert "@all" not in z and "@**" not in z


def test_weather_alert_names_parcels_capped():
    w = [dict(WEATHER, parcel_names=["Olivar Norte", "La Vega"])]
    text = render.email(rep([task("1")], weather=w), "es", PREFS, APP)["text"]
    assert "Aviso meteorológico grave (previsión): Olivar Norte, La Vega" in text
    w = [dict(WEATHER, parcel_names=["A", "B", "C", "D", "E"])]
    text = render.email(rep([task("1")], weather=w), "es", PREFS, APP)["text"]
    assert "(previsión): A, B, C y 2 más" in text
    en = render.email(rep([task("1")], weather=w), "en", PREFS, APP)["text"]
    assert "A, B, C and 2 more" in en
