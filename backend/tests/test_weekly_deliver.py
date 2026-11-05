"""Weekly report delivery: recipients, claims, channels, no email in logs."""
import json
import logging
from datetime import date

import pytest

from app.config import Settings
from app.dispatcher import adapters
from app.digest.weekly import deliver, store
from tests.test_weekly_compose import contrib, gathered, src, task
from app.digest.weekly.compose import build

T = "tenant-a"
WEEK = "2026-W46"
MAIL = {"u1": "ana@example.org", "u2": "bea@example.org", "u3": "carl@example.org"}


def _user(uid, enabled=True, email=True, locale="es", roles=("TenantAdmin",)):
    return {"user_id": uid, "email": MAIL.get(uid, f"{uid}@example.org") if email else None,
            "locale": locale, "roles": list(roles), "enabled": enabled}


class Resp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code, self._p, self.text = status, payload, text

    def json(self):
        return self._p


class Env:
    def __init__(self):
        self.users = [_user("u1"), _user("u2")]
        self.users_status = 200
        self.rows = {}
        self.opted_out = set()
        self.channels = {"email": True, "zulip": True}
        self.tenant_cfg = {"push": {"lang": "en"}, "zulip": {"enabled": True}}
        self.calls = []  # (method, url, kwargs)
        self.fail = {}  # url-suffix -> status
        self.email_fail_for = set()

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return Resp(self.users_status, {"users": self.users})

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        body = kw.get("json") or {}
        if url.endswith("/send/report") and body.get("email") in self.email_fail_for:
            return Resp(500, text="boom")
        for suffix, status in self.fail.items():
            if url.endswith(suffix):
                return Resp(status, {}, "err")
        return Resp(200, {"status": "sent"})

    def posts(self, suffix):
        return [c for c in self.calls if c[0] == "POST" and c[1].endswith(suffix)]

    # store fakes
    def claim(self, tenant, week, uid, ch):
        k = (tenant, week, uid, ch)
        if k in self.rows and self.rows[k] != "failed":
            return False
        self.rows[k] = "sending"
        return True

    def finish(self, tenant, week, uid, ch, status, error=None):
        self.rows[(tenant, week, uid, ch)] = status


@pytest.fixture()
def env(monkeypatch):
    e = Env()
    monkeypatch.setattr("requests.get", e.get)
    monkeypatch.setattr("requests.post", e.post)
    monkeypatch.setattr(store, "claim_delivery", e.claim)
    monkeypatch.setattr(store, "finish_delivery", e.finish)
    monkeypatch.setattr(store, "is_opted_out", lambda t, u, category="weekly_report": u in e.opted_out)
    monkeypatch.setattr(store, "get_channels", lambda t: e.channels)
    monkeypatch.setattr(deliver, "_tenant_cfg", lambda t: e.tenant_cfg)
    set_settings(monkeypatch)
    return e


def set_settings(monkeypatch, **kw):
    base = dict(report_prefs_secret="s3cret", public_api_url="https://api.example.test",
                public_app_url="https://app.example.test", internal_service_secret="int",
                email_service_url="http://email", push_service_url="http://push",
                zulip_service_url="http://zulip", tenant_user_api_url="http://users",
                default_lang="es")
    base.update(kw)
    monkeypatch.setattr(deliver, "get_settings", lambda: Settings(_env_file=None, **base))


@pytest.fixture()
def report():
    return build(gathered([src(c=contrib([task("1"), task("2")]))]), date(2026, 11, 9), WEEK)


def test_push_adapter_legacy_body_unchanged(monkeypatch):
    seen = {}

    def post(url, json=None, headers=None, timeout=None):
        seen["body"] = json
        return Resp(200)

    monkeypatch.setattr(adapters.requests, "post", post)
    alert = {"tenant_id": "t", "title": "A", "summary": "B", "data": {"x": 1}}
    adapters.push_adapter(alert, {"enabled": True}, "http://p", "s")
    legacy = {"tenant_id": "t", "title": "A", "body": "B", "data": {"x": 1}}
    assert json_bytes(seen["body"]) == json_bytes(legacy)
    adapters.push_adapter({**alert, "user_ids": ["u1"], "channel_id": "silent"}, {"enabled": True}, "http://p", "s")
    assert seen["body"]["user_ids"] == ["u1"] and seen["body"]["channelId"] == "silent"


def json_bytes(d):
    return json.dumps(d, sort_keys=False).encode()


def test_farmer_never_requested(env, report):
    deliver.deliver(T, report, include_zulip=True)
    get = [c for c in env.calls if c[0] == "GET"][0]
    assert get[1] == f"http://users/internal/tenants/{T}/users"
    assert get[2]["params"]["roles"] == "TenantAdmin,TechnicalConsultant"
    assert get[2]["headers"]["X-Internal-Service-Secret"] == "int"


def test_opted_out_gets_no_email_no_push(env, report):
    env.opted_out = {"u1"}
    assert deliver.deliver(T, report, include_zulip=True) is True
    assert [c[2]["json"]["email"] for c in env.posts("/send/report")] == [MAIL["u2"]]
    assert env.posts("/send/push")[0][2]["json"]["user_ids"] == ["u2"]


def test_disabled_or_no_email_skipped(env, report):
    env.users = [_user("u1", enabled=False), _user("u2", email=False), _user("u3")]
    assert deliver.deliver(T, report, include_zulip=True) is True
    assert env.rows[(T, WEEK, "u1", "email")] == "skipped"
    assert env.rows[(T, WEEK, "u2", "email")] == "skipped"
    assert [c[2]["json"]["email"] for c in env.posts("/send/report")] == [MAIL["u3"]]
    assert sorted(env.posts("/send/push")[0][2]["json"]["user_ids"]) == ["u2", "u3"]


def test_email_channel_off_no_email(env, report):
    env.channels = {"email": False, "zulip": False}
    deliver.deliver(T, report, include_zulip=True)
    assert env.posts("/send/report") == []
    assert env.posts("/send/push")


def test_zulip_off_no_zulip(env, report):
    env.channels = {"email": True, "zulip": False}
    deliver.deliver(T, report, include_zulip=True)
    assert env.posts("/internal/message") == []
    env.channels = {"email": True, "zulip": True}
    env.tenant_cfg = {"zulip": {"enabled": False}}
    deliver.deliver("tenant-b", report, include_zulip=True)
    assert env.posts("/internal/message") == []


@pytest.mark.parametrize("missing", ["report_prefs_secret", "public_api_url"])
def test_missing_prefs_secret_or_api_url_blocks_email_only(env, report, monkeypatch, caplog, missing):
    set_settings(monkeypatch, **{missing: ""})
    with caplog.at_level(logging.CRITICAL):
        assert deliver.deliver(T, report, include_zulip=True) is False
    assert env.posts("/send/report") == []
    assert env.posts("/send/push")
    assert sum(1 for r in caplog.records if r.levelno == logging.CRITICAL) == 1
    assert not [k for k in env.rows if k[3] == "email"]
    # after the config is fixed, email goes out
    set_settings(monkeypatch)
    assert deliver.deliver(T, report, include_zulip=True) is True
    assert len(env.posts("/send/report")) == 2


def test_recipient_failure_no_email_no_push(env, report):
    env.users_status = 503
    assert deliver.deliver(T, report, include_zulip=True) is False
    assert env.posts("/send/report") == [] and env.posts("/send/push") == []
    with pytest.raises(RuntimeError):
        deliver.fetch_recipients(T)


def test_claim_prevents_duplicate(env, report):
    deliver.deliver(T, report, include_zulip=True)
    deliver.deliver(T, report, include_zulip=True)
    assert len(env.posts("/send/report")) == 2
    assert len(env.posts("/send/push")) == 1
    assert len(env.posts("/internal/message")) == 1


def test_failed_retried_only_that_user(env, report):
    env.email_fail_for = {MAIL["u2"]}
    assert deliver.deliver(T, report, include_zulip=True) is False
    assert env.rows[(T, WEEK, "u2", "email")] == "failed"
    env.email_fail_for = set()
    assert deliver.deliver(T, report, include_zulip=True) is True
    sent = [c[2]["json"]["email"] for c in env.posts("/send/report")]
    assert sent == [MAIL["u1"], MAIL["u2"], MAIL["u2"]]


def test_only_user_id(env, report):
    deliver.deliver(T, report, only_user_id="u2", include_zulip=False)
    assert [c[2]["json"]["email"] for c in env.posts("/send/report")] == [MAIL["u2"]]
    assert env.posts("/send/push")[0][2]["json"]["user_ids"] == ["u2"]
    assert env.posts("/internal/message") == []


def test_email_payload(env, report):
    deliver.deliver(T, report, include_zulip=True)
    c = env.posts("/send/report")[0]
    assert c[2]["headers"] == {"X-Internal-Service-Secret": "int"}
    b = c[2]["json"]
    assert set(b) == {"email", "subject", "content_html", "text", "title", "list_unsubscribe_url"}
    assert b["list_unsubscribe_url"].startswith(
        "https://api.example.test/api/notifications/public/report-preferences?")
    assert "u=u1" in b["list_unsubscribe_url"] and "lang=es" in b["list_unsubscribe_url"]


def test_push_payload(env, report):
    from app.digest.weekly import render
    env.opted_out = {"u2"}
    deliver.deliver(T, report, include_zulip=True)
    c = env.posts("/send/push")[0]
    assert c[2]["headers"] == {"X-Internal-Secret": "int"}
    b = c[2]["json"]
    p = render.plain(report, "en")
    assert b["title"] == p["title"] and b["body"] == p["body"]
    assert b["user_ids"] == ["u1"] and b["tenant_id"] == T and b["channelId"] == "silent"
    assert b["data"] == {"alertType": "weekly_report", "entityId": WEEK, "parcelId": None,
                         "plain": {"title": p["title"], "body": p["body"]}, "urgency": "silent",
                         "action": {"kind": "open_report", "params": {"reportId": WEEK}}}


def test_zulip_stream_rule(env, report):
    assert deliver.zulip_stream("acme", {}) == "tenant-acme-alerts"
    assert deliver.zulip_stream("acme", None) == "tenant-acme-alerts"
    assert deliver.zulip_stream("acme", {"stream": "tenant-acme-general"}) == "tenant-acme-general"
    assert deliver.zulip_stream("acme", {"stream": "alerts"}) is None
    assert deliver.zulip_stream("acme", {"stream": "tenant-other-alerts"}) is None
    for bad in ("tenant-acme-x-alerts", "tenant-acme-", "tenant-acme-custom", "alerts"):
        assert deliver.zulip_stream("acme", {"stream": bad}) is None
    env.tenant_cfg = {"zulip": {"enabled": True, "stream": "alerts"}}
    deliver.deliver(T, report, include_zulip=True)
    assert env.posts("/internal/message") == []
    assert env.rows[(T, WEEK, "", "zulip")] == "skipped"
    env.tenant_cfg = {"zulip": {"enabled": True}}
    deliver.deliver("tenant-b", report, include_zulip=True)
    z = env.posts("/internal/message")[0][2]["json"]
    assert z["stream"] == "tenant-tenant-b-alerts"
    assert z["topic"] == "Informe semanal"


def test_no_email_in_logs(env, report, caplog):
    env.email_fail_for = {MAIL["u2"]}
    with caplog.at_level(logging.DEBUG):
        deliver.deliver(T, report, include_zulip=True)
        env.users_status = 500
        deliver.deliver(T, report, include_zulip=True)
    text = caplog.text + json.dumps({str(k): v for k, v in env.rows.items()})
    for addr in MAIL.values():
        assert addr not in text


def test_lang():
    assert deliver.pick_user_lang("eu", "es") == "eu"
    assert deliver.pick_user_lang("en-GB", "es") == "en"
    assert deliver.pick_user_lang("ca", "es") == "es"
    assert deliver.pick_user_lang(None, "es") == "es"
    assert deliver.pick_user_lang("ca", "xx") == "es"


@pytest.mark.parametrize("bad", ["tenant-acme-x-alerts", "tenant-acme-", "tenant-acme-custom", "alerts"])
def test_bad_streams_recorded_skipped(env, report, bad):
    env.tenant_cfg = {"zulip": {"enabled": True, "stream": bad}}
    assert deliver.deliver("acme", report, include_zulip=True) is True
    assert env.posts("/internal/message") == []
    assert env.rows[("acme", WEEK, "", "zulip")] == "skipped"


def test_push_store_error_does_not_block_zulip(env, report, monkeypatch):
    def finish(tenant, week, uid, ch, status, error=None):
        if ch == "push":
            raise RuntimeError("db down")
        env.finish(tenant, week, uid, ch, status, error)

    monkeypatch.setattr(store, "finish_delivery", finish)
    assert deliver.deliver(T, report, include_zulip=True) is False
    assert len(env.posts("/internal/message")) == 1


def test_zulip_default_off_with_only_user(env, report):
    deliver.deliver(T, report, only_user_id="u1")
    assert env.posts("/internal/message") == []
    deliver.deliver(T, report, only_user_id="u1", include_zulip=True)
    assert len(env.posts("/internal/message")) == 1


def test_failed_push_batch_retried(env, report, monkeypatch):
    errors = {}
    monkeypatch.setattr(store, "finish_delivery",
                        lambda t, w, u, c, st, error=None: (env.finish(t, w, u, c, st, error),
                                                            errors.__setitem__((u, c), error)))
    env.fail = {"/send/push": 502}
    assert deliver.deliver(T, report) is False
    assert env.rows[(T, WEEK, "u1", "push")] == env.rows[(T, WEEK, "u2", "push")] == "failed"
    assert errors[("u1", "push")] == "HTTP 502"
    env.fail = {}
    env.rows[(T, WEEK, "u2", "push")] = "sent"
    assert deliver.deliver(T, report) is True
    assert [c[2]["json"]["user_ids"] for c in env.posts("/send/push")] == [["u1", "u2"], ["u1"]]
