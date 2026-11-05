import hmac
import hashlib

import pytest

from app.digest.weekly import prefs_token as pt

S = "unit-secret"
NOW = 1_800_000_000


def test_format():
    tok = pt.sign("u1", "tenant-a", NOW + 100, S)
    digest, exp = tok.split(":")
    assert len(digest) == 64 and int(digest, 16) >= 0
    assert exp == str(NOW + 100)
    expected = hmac.new(S.encode(), f"u1|tenant-a|{NOW + 100}".encode(), hashlib.sha256).hexdigest()
    assert digest == expected
    assert pt.verify(tok, "u1", "tenant-a", S, NOW)


def test_uses_compare_digest(monkeypatch):
    calls = []
    real = hmac.compare_digest
    monkeypatch.setattr(pt.hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    pt.verify(pt.sign("u1", "tenant-a", NOW + 5, S), "u1", "tenant-a", S, NOW)
    assert calls


def test_rejects_tampered():
    tok = pt.sign("u1", "tenant-a", NOW + 100, S)
    bad = ("0" if tok[0] != "0" else "1") + tok[1:]
    assert not pt.verify(bad, "u1", "tenant-a", S, NOW)
    # extended expiry with the old digest
    assert not pt.verify(tok.split(":")[0] + f":{NOW + 9999}", "u1", "tenant-a", S, NOW)


def test_rejects_other_user_and_tenant():
    tok = pt.sign("u1", "tenant-a", NOW + 100, S)
    assert not pt.verify(tok, "u2", "tenant-a", S, NOW)
    assert not pt.verify(tok, "u1", "tenant-b", S, NOW)


def test_rejects_expired():
    tok = pt.sign("u1", "tenant-a", NOW - 1, S)
    assert not pt.verify(tok, "u1", "tenant-a", S, NOW)


@pytest.mark.parametrize("tok", ["", "nocolon", "abc:", ":123", "abc:notnum", "a:b:c", "x" * 64 + ":-5", "é:1"])
def test_rejects_malformed(tok):
    assert pt.verify(tok, "u1", "tenant-a", S, NOW) is False


def test_empty_secret_never_verifies():
    tok = pt.sign("u1", "tenant-a", NOW + 100, "x")
    assert not pt.verify(tok, "u1", "tenant-a", "", NOW)
    forged = hmac.new(b"", f"u1|tenant-a|{NOW + 100}".encode(), hashlib.sha256).hexdigest() + f":{NOW + 100}"
    assert not pt.verify(forged, "u1", "tenant-a", "", NOW)
    with pytest.raises(ValueError):
        pt.sign("u1", "tenant-a", NOW + 100, "")


def test_pipe_in_ids_rejected():
    tok = pt.sign("u1", "tenant-a", NOW + 100, S)
    assert not pt.verify(tok, "u1|tenant-a", "x", S, NOW)


def test_preferences_url():
    url = pt.preferences_url("https://api.example.org/api/notifications", "u 1", "tenant-a", "eu", S, NOW)
    assert url.startswith("https://api.example.org/api/notifications/public/report-preferences?")
    from urllib.parse import urlparse, parse_qs
    q = parse_qs(urlparse(url).query)
    assert q["u"] == ["u 1"] and q["t"] == ["tenant-a"] and q["lang"] == ["eu"]
    assert pt.verify(q["token"][0], "u 1", "tenant-a", S, NOW)
    assert int(q["token"][0].split(":")[1]) == NOW + 365 * 86400
