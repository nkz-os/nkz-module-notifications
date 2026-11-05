from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.digest.weekly import prefs_token as pt

SECRET = "unit-secret"
BASE = "/api/notifications/public/report-preferences"


class FakeStore:
    def __init__(self):
        self.opted_out = set()
        self.writes = 0

    def is_opted_out(self, tenant_id, user_id, category="weekly_report"):
        return (tenant_id, user_id) in self.opted_out

    def set_pref(self, tenant_id, user_id, enabled, category="weekly_report"):
        self.writes += 1
        (self.opted_out.discard if enabled else self.opted_out.add)((tenant_id, user_id))


@pytest.fixture
def store():
    s = FakeStore()
    with patch("app.api.public.store", s):
        yield s


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("REPORT_PREFS_SECRET", SECRET)
    get_settings.cache_clear()
    from app.main import create_app
    yield TestClient(create_app())
    get_settings.cache_clear()


def _qs(user="u1", tenant="tenant-a", lang="es", token=None, secret=SECRET):
    import time
    from urllib.parse import urlencode
    tok = token if token is not None else pt.sign(user, tenant, int(time.time()) + 3600, secret)
    return urlencode({"u": user, "t": tenant, "lang": lang, "token": tok})


def _assert_headers(r):
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["x-robots-tag"] == "noindex"
    assert r.headers["content-security-policy"] == "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'"


def test_get_does_not_change_state(client, store):
    for _ in range(3):
        r = client.get(f"{BASE}?{_qs()}")
        assert r.status_code == 200
    assert store.writes == 0 and not store.opted_out


def test_post_unsubscribe_then_resubscribe(client, store):
    r = client.post(f"{BASE}?{_qs()}", content="action=unsubscribe",
                    headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200 and ("tenant-a", "u1") in store.opted_out
    r = client.post(f"{BASE}?{_qs()}", content="action=subscribe",
                    headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200 and not store.opted_out


def test_post_unknown_action_changes_nothing(client, store):
    r = client.post(f"{BASE}?{_qs()}", content="action=drop")
    assert r.status_code == 400 and store.writes == 0
    _assert_headers(r)
    r = client.post(f"{BASE}?{_qs()}", content="")
    assert r.status_code == 400 and store.writes == 0


def test_rfc8058_one_click(client, store):
    r = client.post(f"{BASE}?{_qs()}", content="List-Unsubscribe=One-Click",
                    headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200 and ("tenant-a", "u1") in store.opted_out


def test_bad_token_400_no_change(client, store):
    other = pt.sign("u1", "tenant-a", 9_999_999_999, "other-secret")
    for method in ("get", "post"):
        r = getattr(client, method)(f"{BASE}?{_qs(token=other)}", **({"content": "action=unsubscribe"} if method == "post" else {}))
        assert r.status_code == 400
        _assert_headers(r)
    r = client.post(f"{BASE}?u=u1&t=tenant-a", content="action=unsubscribe")
    assert r.status_code == 400
    _assert_headers(r)
    assert store.writes == 0


def test_token_for_other_user_rejected(client, store):
    tok = pt.sign("u2", "tenant-a", 9_999_999_999, SECRET)
    r = client.post(f"{BASE}?{_qs(user='u1', token=tok)}", content="action=unsubscribe")
    assert r.status_code == 400 and store.writes == 0


def test_unset_secret_rejects(monkeypatch, store):
    monkeypatch.setenv("REPORT_PREFS_SECRET", "")
    get_settings.cache_clear()
    from app.main import create_app
    c = TestClient(create_app())
    r = c.post(f"{BASE}?{_qs()}", content="action=unsubscribe")
    assert r.status_code == 400 and store.writes == 0
    get_settings.cache_clear()


def test_page_headers(client, store):
    _assert_headers(client.get(f"{BASE}?{_qs()}"))
    _assert_headers(client.post(f"{BASE}?{_qs()}", content="action=unsubscribe"))


def test_no_internal_auth_required(client, store):
    assert client.get(f"{BASE}?{_qs()}").status_code == 200  # no X-Internal-Service-Secret


def test_page_escapes_and_lang(client, store):
    r = client.get(f"{BASE}?{_qs(lang='eu')}")
    assert 'lang="eu"' in r.text
    r_es = client.get(f"{BASE}?{_qs(lang='es')}")
    assert r.text != r_es.text
    r_fr = client.get(f"{BASE}?{_qs(lang='fr')}")
    assert 'lang="es"' in r_fr.text
    evil = "<script>alert(1)</script>"
    r = client.get(f"{BASE}?{_qs(user=evil)}")
    assert "<script>alert(1)" not in r.text
    r = client.get(f"{BASE}?{_qs(user=evil, token='bad')}")
    assert "<script>alert(1)" not in r.text
    import re
    visible = re.sub(r"<[^>]*>", " ", r_es.text)  # the form action URL (an attribute) must carry the ids; text must not
    assert "u1" not in visible and "tenant-a" not in visible


def test_page_reflects_state(client, store):
    store.opted_out.add(("tenant-a", "u1"))
    r = client.get(f"{BASE}?{_qs()}")
    assert 'value="subscribe"' in r.text and 'value="unsubscribe"' not in r.text
