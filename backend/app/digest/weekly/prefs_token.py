"""Signed token for the public weekly-report preferences page.

Canonical platform format: payload `{user_id}|{tenant_id}|{expiry}`, output
`{HMAC-SHA256 hexdigest}:{expiry}`, full digest, constant-time comparison.
Uses a dedicated secret (never HMAC_SECRET).
"""
import hashlib
import hmac
from urllib.parse import urlencode

TOKEN_TTL_SECONDS = 365 * 86400
PATH = "/public/report-preferences"


def _digest(user_id: str, tenant_id: str, expiry: int, secret: str) -> str:
    payload = f"{user_id}|{tenant_id}|{expiry}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def sign(user_id: str, tenant_id: str, expiry: int, secret: str) -> str:
    if not secret:
        raise ValueError("report preferences secret is empty")
    if "|" in user_id or "|" in tenant_id:
        raise ValueError("identifiers must not contain '|'")
    return f"{_digest(user_id, tenant_id, expiry, secret)}:{int(expiry)}"


def verify(token: str, user_id: str, tenant_id: str, secret: str, now: int) -> bool:
    """True only for a well-formed, unexpired token signed for this user and tenant. Never raises."""
    try:
        if not secret or not isinstance(token, str):
            return False
        if "|" in user_id or "|" in tenant_id:
            return False
        digest, sep, exp_s = token.partition(":")
        if not sep or len(digest) != 64 or not exp_s.isascii() or not exp_s.isdigit():
            return False
        expiry = int(exp_s)
        expected = _digest(user_id, tenant_id, expiry, secret)
        ok = hmac.compare_digest(digest.encode("ascii", "replace"), expected.encode())
        return ok and expiry > now
    except Exception:
        return False


def preferences_url(base: str, user_id: str, tenant_id: str, lang: str, secret: str, now: int) -> str:
    token = sign(user_id, tenant_id, int(now) + TOKEN_TTL_SECONDS, secret)
    query = urlencode({"u": user_id, "t": tenant_id, "lang": lang, "token": token})
    return f"{base.rstrip('/')}{PATH}?{query}"
