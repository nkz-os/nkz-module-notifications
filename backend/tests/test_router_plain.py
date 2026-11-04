"""Plain alert texts: urgency, language by tenant config, push payload."""
from unittest.mock import MagicMock

from app.dispatcher import NotificationDispatcher
from app.dispatcher.router import _is_immediate, alert_to_info, handle_alert, pick_lang

PLAIN = {
    "es": {"title": "Riega hoy", "body": "Parcela seca"},
    "eu": {"title": "Ureztatu gaur", "body": "Lursaila lehorra"},
    "en": {"title": "Irrigate today", "body": "Parcel is dry"},
}


def _alert(alert_type="work_irrigate", severity="high", plain=True, urgency="vibrate",
           action=True, ref="urn:ngsi-ld:AgriParcel:p1", raw=False):
    def prop(v):
        return v if raw else {"type": "Property", "value": v}

    e = {
        "id": f"urn:ngsi-ld:Alert:acmefarm:{alert_type}:p1",
        "type": "Alert",
        "alertType": {"type": "Property", "value": alert_type},
        "severity": {"type": "Property", "value": severity},
        "refEntity": {"type": "Relationship", "object": ref},
        "status": {"type": "Property", "value": "active"},
    }
    if plain:
        e["plain"] = prop(PLAIN)
    if urgency:
        e["urgency"] = prop(urgency)
    if action:
        e["action"] = prop({"kind": "open_parcel", "params": {}})
    return e


def test_info_has_plain_fields_normalized_and_raw():
    for raw in (False, True):
        info = alert_to_info(_alert(raw=raw))
        assert info["plain"] == PLAIN
        assert info["urgency"] == "vibrate"
        assert info["action"] == {"kind": "open_parcel", "params": {}}
        assert info["parcel_id"] == "urn:ngsi-ld:AgriParcel:p1"


def test_info_without_plain_fields_is_none():
    info = alert_to_info(_alert(plain=False, urgency=None, action=False, ref="urn:ngsi-ld:Device:d1"))
    assert info["plain"] is None and info["urgency"] is None
    assert info["action"] is None and info["parcel_id"] is None


def test_info_rejects_invalid_values():
    e = _alert()
    e["plain"] = {"type": "Property", "value": "text"}
    e["urgency"] = {"type": "Property", "value": "loud"}
    e["action"] = {"type": "Property", "value": {"params": {}}}
    info = alert_to_info(e)
    assert info["plain"] is None and info["urgency"] is None and info["action"] is None
    e["plain"] = {"type": "Property", "value": {"es": {"title": "a"}, "xx": {"title": "a", "body": "b"}}}
    assert alert_to_info(e)["plain"] is None


def test_is_immediate_by_urgency():
    base = {"alert_type": "rust", "severity": "low"}
    assert _is_immediate({**base, "urgency": "vibrate"}) is True
    assert _is_immediate({"alert_type": "frost", "severity": "critical", "urgency": "silent"}) is False
    assert _is_immediate({"alert_type": "frost", "severity": "high", "urgency": None}) is True
    assert _is_immediate({**base, "urgency": None}) is False


def test_pick_lang():
    assert pick_lang(PLAIN, "eu")["title"] == "Ureztatu gaur"
    assert pick_lang({"es": PLAIN["es"]}, "eu") == PLAIN["es"]
    assert pick_lang({"en": PLAIN["en"]}, "eu") == PLAIN["en"]
    assert pick_lang({}, "es") is None


def _capture(monkeypatch):
    disp = MagicMock()
    disp.has_delivered.return_value = False
    monkeypatch.setattr("app.dispatcher.NotificationDispatcher", lambda: disp)
    return disp


def test_handle_alert_payload(monkeypatch):
    disp = _capture(monkeypatch)
    assert handle_alert("acmefarm", _alert()) == "immediate"
    payload = disp.dispatch.call_args.args[3]
    assert payload["channel_id"] == "vibrate"
    assert payload["plain_all"] == PLAIN
    d = payload["data"]
    assert d["plain"] is None and d["urgency"] == "vibrate"
    assert d["action"] == {"kind": "open_parcel", "params": {}}
    assert d["screen"] == "ParcelDetail" and d["params"] == {"parcelId": "urn:ngsi-ld:AgriParcel:p1"}
    assert d["parcelId"] == "urn:ngsi-ld:AgriParcel:p1"


def test_handle_alert_legacy_frost_payload(monkeypatch):
    disp = _capture(monkeypatch)
    assert handle_alert("acmefarm", _alert("frost", "critical", plain=False, urgency=None, action=False)) == "immediate"
    p = disp.dispatch.call_args.args[3]
    assert p["title"] == "Notification — frost" and p["plain_all"] is None
    assert "channel_id" not in p
    assert "urgency" not in p["data"] and "action" not in p["data"]


def test_producer_without_plain_is_queued_never_vibrate(monkeypatch):
    queued = {}
    monkeypatch.setattr("app.dispatcher.router._queue_for_digest",
                        lambda tid, info, alert_name="", parcel_name="": queued.update(info) or True)
    disp = _capture(monkeypatch)
    assert handle_alert("acmefarm", _alert("sensor_health", "medium", plain=False, urgency=None, action=False)) == "queued"
    disp.dispatch.assert_not_called()
    assert queued["urgency"] is None


def test_silent_goes_to_digest(monkeypatch):
    monkeypatch.setattr("app.dispatcher.router._queue_for_digest", lambda *a, **k: True)
    disp = _capture(monkeypatch)
    assert handle_alert("acmefarm", _alert("frost", "critical", urgency="silent")) == "queued"
    disp.dispatch.assert_not_called()


def _dispatch(monkeypatch, push_cfg, monkeypatch_payload=None):
    seen = {}

    def fake_push(alert, config, **kw):
        seen.update(alert)
        from app.dispatcher.adapters import DeliveryResult
        return DeliveryResult("push", "sent")

    monkeypatch.setattr("app.dispatcher.adapters.push_adapter", fake_push)
    d = NotificationDispatcher()
    monkeypatch.setattr(d, "_get_channels", lambda t: {"push": push_cfg})
    monkeypatch.setattr(d, "_record_delivery", lambda *a, **k: None)
    payload = {"id": "x", "title": "T", "summary": "S", "data": {"plain": None}, "channel_id": "vibrate",
               "plain_all": PLAIN}
    d.dispatch("acmefarm", "work_irrigate", "high", payload)
    return seen


def test_dispatch_language_eu(monkeypatch):
    seen = _dispatch(monkeypatch, {"enabled": True, "lang": "eu"})
    assert seen["title"] == "Ureztatu gaur" and seen["summary"] == "Lursaila lehorra"
    assert seen["data"]["plain"] == PLAIN["eu"]


def test_dispatch_invalid_lang_falls_back_to_default_lang(monkeypatch):
    seen = _dispatch(monkeypatch, {"enabled": True, "lang": "fr"})
    assert seen["title"] == "Riega hoy" and seen["data"]["plain"] == PLAIN["es"]


def test_dispatch_invalid_lang_uses_settings_default(monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "default_lang", "en")
    seen = _dispatch(monkeypatch, {"enabled": True, "lang": "fr"})
    assert seen["title"] == "Irrigate today"


def test_legacy_alert_push_has_no_channel_or_urgency(monkeypatch):
    from app.dispatcher.adapters import DeliveryResult
    seen = {}

    def fake_post(url, json=None, **kw):
        seen.update(json)
        return MagicMock(status_code=200, text="")

    monkeypatch.setattr("requests.post", fake_post)
    from app.dispatcher.adapters import push_adapter
    disp = _capture(monkeypatch)
    handle_alert("acmefarm", _alert("frost", "critical", plain=False, urgency=None, action=False))
    payload = disp.dispatch.call_args.args[3]
    r = push_adapter({k: v for k, v in payload.items() if k != "plain_all"}
                     | {"tenant_id": "acmefarm"}, {"enabled": True}, push_service_url="http://x", internal_secret="s")
    assert isinstance(r, DeliveryResult)
    assert "channelId" not in seen
    assert "urgency" not in seen.get("data", {})
    assert seen["title"] == "Notification — frost"


def test_dedup_released_on_resolve_and_notifies_again(monkeypatch):
    sent, delivered = [], set()

    class FakeDisp:
        def has_delivered(self, aid, sev):
            return aid in delivered

        def dispatch(self, tenant, atype, sev, payload):
            delivered.add(payload["id"])
            sent.append(payload["id"])

        def release_delivery(self, tenant, aid):
            delivered.discard(aid)

    monkeypatch.setattr("app.dispatcher.NotificationDispatcher", FakeDisp)
    active = _alert()
    resolved = _alert()
    resolved["status"] = {"type": "Property", "value": "resolved"}
    assert handle_alert("acmefarm", active) == "immediate"
    assert handle_alert("acmefarm", active) == "skipped"
    assert handle_alert("acmefarm", resolved) == "skipped"
    assert not delivered
    assert handle_alert("acmefarm", active) == "immediate"
    assert len(sent) == 2


def test_release_delivery_sql_is_tenant_scoped(monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr("app.dispatcher.get_conn", lambda: conn)
    NotificationDispatcher().release_delivery("acmefarm", "urn:x")
    sql, params = conn.cursor.return_value.__enter__.return_value.execute.call_args.args
    assert "DELETE FROM notifications.alert_deliveries" in sql and "tenant_id" in sql
    assert params == ("urn:x", "acmefarm")
    conn.commit.assert_called_once()


def test_dispatch_missing_lang_uses_default(monkeypatch):
    seen = _dispatch(monkeypatch, {"enabled": True})
    assert seen["title"] == "Riega hoy"


def test_dispatch_without_plain_all_keeps_texts(monkeypatch):
    seen = {}

    def fake_push(alert, config, **kw):
        seen.update(alert)
        from app.dispatcher.adapters import DeliveryResult
        return DeliveryResult("push", "sent")

    monkeypatch.setattr("app.dispatcher.adapters.push_adapter", fake_push)
    d = NotificationDispatcher()
    monkeypatch.setattr(d, "_get_channels", lambda t: {"push": {"enabled": True, "lang": "eu"}})
    monkeypatch.setattr(d, "_record_delivery", lambda *a, **k: None)
    d.dispatch("acmefarm", "frost", "high", {"id": "x", "title": "T", "summary": "S", "data": {}})
    assert seen["title"] == "T" and seen["summary"] == "S"


def test_push_adapter_sends_channel_id(monkeypatch):
    from app.dispatcher.adapters import push_adapter
    sent = {}
    resp = MagicMock(status_code=200)
    monkeypatch.setattr("app.dispatcher.adapters.requests.post",
                        lambda url, json=None, **k: sent.update(json) or resp)
    push_adapter({"tenant_id": "acmefarm", "title": "t", "summary": "s", "data": {}, "channel_id": "vibrate"},
                 {"enabled": True}, "http://push", "sec")
    assert sent["channelId"] == "vibrate"
    sent.clear()
    push_adapter({"tenant_id": "acmefarm", "title": "t", "summary": "s", "data": {}}, {"enabled": True}, "http://push", "sec")
    assert "channelId" not in sent


def test_vibrate_without_plain_is_queued_and_silent(monkeypatch):
    queued = {}
    monkeypatch.setattr("app.dispatcher.router._queue_for_digest",
                        lambda tid, info, alert_name="", parcel_name="": queued.update(info) or True)
    disp = _capture(monkeypatch)
    for plain in (None, {"fr": {"title": "a", "body": "b"}}):
        e = _alert("rust", "low", plain=False)
        if plain:
            e["plain"] = {"type": "Property", "value": plain}
        info = alert_to_info(e)
        assert info["urgency"] is None
        assert handle_alert("acmefarm", e) == "queued"
    disp.dispatch.assert_not_called()


def test_vibrate_without_plain_extreme_keeps_legacy_no_channel(monkeypatch):
    disp = _capture(monkeypatch)
    assert handle_alert("acmefarm", _alert("frost", "high", plain=False)) == "immediate"
    assert "channel_id" not in disp.dispatch.call_args.args[3]


def test_non_push_adapters_get_no_internal_fields(monkeypatch):
    from app.dispatcher.adapters import DeliveryResult
    seen = {}

    def mk(name):
        def f(alert, config, **kw):
            seen[name] = dict(alert)
            return DeliveryResult(name, "sent")
        return f

    for n in ("email", "push", "zulip", "webhook", "telegram"):
        monkeypatch.setattr(f"app.dispatcher.adapters.{n}_adapter", mk(n))
    d = NotificationDispatcher()
    on = {"enabled": True}
    monkeypatch.setattr(d, "_get_channels", lambda t: {n: on for n in ("email", "push", "zulip", "webhook", "telegram")})
    monkeypatch.setattr(d, "_record_delivery", lambda *a, **k: None)
    d.dispatch("acmefarm", "x", "high", {"id": "x", "title": "T", "summary": "S", "data": {},
                                         "channel_id": "vibrate", "plain_all": PLAIN})
    for n in ("email", "zulip", "webhook", "telegram"):
        assert "channel_id" not in seen[n] and "plain_all" not in seen[n]
        assert seen[n]["data"]["plain"] == PLAIN["es"]
    assert seen["push"]["channel_id"] == "vibrate"
