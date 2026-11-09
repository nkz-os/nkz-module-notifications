"""User-facing copy of the weekly report (spec 5). es is the fixed copy; en is a direct translation.

# ASSUMPTION: eu wording is ours — confirm before shipping
"""
LANGS = ("es", "eu", "en")
DEFAULT_LANG = "es"

T = {
    "es": {
        "count_one": "1 tarea", "count_many": "{n} tareas",
        "subj_tasks": "Esta semana: {count} en {farm}", "subj_tasks_nofarm": "Esta semana: {count}",
        "count_alert_one": "1 aviso", "count_alert_many": "{n} avisos",
        "subj_alerts": "Esta semana: {count} en {farm}", "subj_alerts_nofarm": "Esta semana: {count}",
        "subj_none": "Esta semana no hay nada urgente en {farm}", "subj_none_nofarm": "Esta semana no hay nada urgente",
        "unk_count_one": "1 parcela", "unk_count_many": "{n} parcelas",
        "subj_unknown": "Sin evaluación reciente en {count} de {farm}", "subj_unknown_nofarm": "Sin evaluación reciente en {count}",
        "unknown_one": "1 parcela sin evaluación reciente.", "unknown_many": "{n} parcelas sin evaluación reciente.",
        "subj_partial": "Informe incompleto: {count} en {farm}", "subj_partial_nofarm": "Informe incompleto: {count}",
        "subj_partial_none": "Informe incompleto para {farm}", "subj_partial_none_nofarm": "Informe incompleto",
        "partial_line": "Falta parte de los datos: {labels}. No se puede asegurar que no haya nada más que hacer.",
        "no_modules_line": "Ningún módulo aporta tareas a este informe. No se puede asegurar que no haya nada que hacer.",
        "alerts_label": "avisos activos",
        "sec_todo": "QUÉ HACER", "sec_changes": "QUÉ HA CAMBIADO", "sec_alerts": "AVISOS ACTIVOS",
        "sec_figures": "LA SEMANA QUE PASÓ, POR PARCELA",
        "grp_now": "Hoy o vencido", "grp_week": "Esta semana", "grp_next": "Próxima semana", "grp_undated": "Sin fecha",
        "rest_one": "La otra parcela, sin novedad.", "rest_many": "Las otras {n} parcelas, sin novedad.",
        "all_one": "La parcela, sin novedad.", "all_many": "Las {n} parcelas, sin novedad.",
        "extra_alerts_one": "1 aviso más en la app.", "extra_alerts_many": "{n} avisos más en la app.",
        "weather_generic": "Aviso meteorológico (previsión)", "weather_sev": "Aviso meteorológico {sev} (previsión)",
        "sev_critical": "muy grave", "sev_severe": "grave", "sev_moderate": "moderado",
        "fig_rain": "lluvia {x} mm", "fig_et0": "evapotranspiración {x} mm", "fig_gdd": "calor acumulado {x} °C·día",
        "origin_estimated": "estimado", "origin_sensor": "medido",
        "unsubscribe": "Dejar de recibir este informe",
        "no_text": "Tarea pendiente, consulta la app para el detalle",
        "more": "y {n} más", "plain_empty": "Sin tareas para las próximas dos semanas.",
        "dec": ",",
        "when_today": "hoy", "when_overdue": "vencida ({d})", "when_week": "esta semana",
        "when_date": "para el {d}", "when_undated": "sin fecha",
    },
    "en": {
        "count_one": "1 task", "count_many": "{n} tasks",
        "subj_tasks": "This week: {count} at {farm}", "subj_tasks_nofarm": "This week: {count}",
        "count_alert_one": "1 alert", "count_alert_many": "{n} alerts",
        "subj_alerts": "This week: {count} at {farm}", "subj_alerts_nofarm": "This week: {count}",
        "subj_none": "Nothing urgent this week at {farm}", "subj_none_nofarm": "Nothing urgent this week",
        "unk_count_one": "1 parcel", "unk_count_many": "{n} parcels",
        "subj_unknown": "No recent assessment for {count} at {farm}", "subj_unknown_nofarm": "No recent assessment for {count}",
        "unknown_one": "1 parcel with no recent assessment.", "unknown_many": "{n} parcels with no recent assessment.",
        "subj_partial": "Incomplete report: {count} at {farm}", "subj_partial_nofarm": "Incomplete report: {count}",
        "subj_partial_none": "Incomplete report for {farm}", "subj_partial_none_nofarm": "Incomplete report",
        "partial_line": "Part of the data is missing: {labels}. We cannot be sure there is nothing else to do.",
        "no_modules_line": "No module contributes tasks to this report. We cannot be sure there is nothing to do.",
        "alerts_label": "active alerts",
        "sec_todo": "WHAT TO DO", "sec_changes": "WHAT HAS CHANGED", "sec_alerts": "ACTIVE ALERTS",
        "sec_figures": "LAST WEEK, BY PARCEL",
        "grp_now": "Today or overdue", "grp_week": "This week", "grp_next": "Next week", "grp_undated": "No date",
        "rest_one": "The other parcel, nothing new.", "rest_many": "The other {n} parcels, nothing new.",
        "all_one": "The parcel, nothing new.", "all_many": "All {n} parcels, nothing new.",
        "extra_alerts_one": "1 more alert in the app.", "extra_alerts_many": "{n} more alerts in the app.",
        "weather_generic": "Weather alert (forecast)", "weather_sev": "{sev} weather alert (forecast)",
        "sev_critical": "Critical", "sev_severe": "Severe", "sev_moderate": "Moderate",
        "fig_rain": "rain {x} mm", "fig_et0": "evapotranspiration {x} mm", "fig_gdd": "accumulated heat {x} °C·day",
        "origin_estimated": "estimated", "origin_sensor": "measured",
        "unsubscribe": "Stop receiving this report",
        "no_text": "Pending task, open the app for details",
        "more": "and {n} more", "plain_empty": "No tasks for the next two weeks.",
        "dec": ".",
        "when_today": "today", "when_overdue": "overdue ({d})", "when_week": "this week",
        "when_date": "for {d}", "when_undated": "no date",
    },
    # ASSUMPTION: eu wording is ours — confirm before shipping
    "eu": {
        "count_one": "zeregin 1", "count_many": "{n} zeregin",
        "subj_tasks": "{farm}: aste honetan {count}", "subj_tasks_nofarm": "Aste honetan: {count}",
        "count_alert_one": "abisu 1", "count_alert_many": "{n} abisu",
        "subj_alerts": "{farm}: aste honetan {count}", "subj_alerts_nofarm": "Aste honetan: {count}",
        "subj_none": "{farm}: aste honetan ez dago ezer premiazkorik", "subj_none_nofarm": "Aste honetan ez dago ezer premiazkorik",
        "unk_count_one": "lursail 1", "unk_count_many": "{n} lursail",
        "subj_unknown": "{farm}: ebaluazio berririk gabe, {count}", "subj_unknown_nofarm": "Ebaluazio berririk gabe: {count}",
        "unknown_one": "Lursail 1 ebaluazio berririk gabe.", "unknown_many": "{n} lursail ebaluazio berririk gabe.",
        "subj_partial": "{farm}: txosten osatugabea, {count}", "subj_partial_nofarm": "Txosten osatugabea: {count}",
        "subj_partial_none": "{farm}: txosten osatugabea", "subj_partial_none_nofarm": "Txosten osatugabea",
        "partial_line": "Datuen zati bat falta da: {labels}. Ezin da ziurtatu beste ezer egiteko ez dagoenik.",
        "no_modules_line": "Ez dago zereginik ekartzen duen modulurik. Ezin da ziurtatu egiteko ezer ez dagoenik.",
        "alerts_label": "abisu aktiboak",
        "sec_todo": "ZER EGIN", "sec_changes": "ZER ALDATU DEN", "sec_alerts": "ABISU AKTIBOAK",
        "sec_figures": "AURREKO ASTEA, LURSAILKA",
        "grp_now": "Gaur edo atzeratuta", "grp_week": "Aste honetan", "grp_next": "Hurrengo astean", "grp_undated": "Datarik gabe",
        "rest_one": "Beste lursaila, aldaketarik gabe.", "rest_many": "Beste {n} lursailak, aldaketarik gabe.",
        "all_one": "Lursaila, aldaketarik gabe.", "all_many": "{n} lursailak, aldaketarik gabe.",
        "extra_alerts_one": "Abisu 1 gehiago aplikazioan.", "extra_alerts_many": "{n} abisu gehiago aplikazioan.",
        "weather_generic": "Eguraldi-abisua (iragarpena)", "weather_sev": "Eguraldi-abisu {sev} (iragarpena)",
        "sev_critical": "oso larria", "sev_severe": "larria", "sev_moderate": "ertaina",
        "fig_rain": "euria {x} mm", "fig_et0": "ebapotranspirazioa {x} mm", "fig_gdd": "bildutako beroa {x} °C·egun",
        "origin_estimated": "zenbatetsia", "origin_sensor": "neurtua",
        "unsubscribe": "Txosten hau jasotzeari utzi",
        "no_text": "Zain dagoen zeregina, xehetasunak aplikazioan",
        "more": "eta {n} gehiago", "plain_empty": "Ez dago zereginik hurrengo bi asteetarako.",
        "dec": ",",
        "when_today": "gaur", "when_overdue": "atzeratuta ({d})", "when_week": "aste honetan",
        "when_date": "{d}rako", "when_undated": "datarik gabe",
    },
}


def norm_lang(lang) -> str:
    return lang if lang in LANGS else DEFAULT_LANG


def t(lang: str, key: str, **kw) -> str:
    s = T[norm_lang(lang)][key]
    return s.format(**kw) if kw else s


def pick_text(texts, lang: str, field: str) -> str:
    """texts = {lang: {field: str}}: lang -> default_lang -> any available; '' if none."""
    if not isinstance(texts, dict):
        return ""
    order = [norm_lang(lang), DEFAULT_LANG, *texts.keys()]
    for code in order:
        entry = texts.get(code)
        value = entry.get(field) if isinstance(entry, dict) else None
        if isinstance(value, str) and value.strip():
            return value
    return ""
