"""
Notifications Backend - Authentication

Trusts gateway-injected headers (X-Tenant-ID, X-User-ID, X-User-Roles).
Delegates to nkz_platform_sdk.auth.require_auth (canonical). /internal/*
routes authenticate via X-Internal-Service-Secret instead.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from nkz_platform_sdk.auth import AuthContext, require_auth as _sdk_require_auth
from nkz_platform_sdk.notify_auth import accept_master_from_env, verify_notification

from app.config import Settings, get_settings

__all__ = [
    "AuthContext",
    "require_auth",
    "get_current_user",
    "get_tenant_id",
    "require_roles",
    "verify_internal_secret",
]

_default_auth_dep = _sdk_require_auth()


def require_auth(roles: Optional[list[str]] = None):
    return _sdk_require_auth(roles=roles)


def get_current_user(auth: AuthContext = _default_auth_dep) -> AuthContext:
    return auth


def get_tenant_id(auth: AuthContext = _default_auth_dep) -> str:
    return auth.tenant_id


def require_roles(*required_roles: str):
    role_dep = _sdk_require_auth(roles=list(required_roles))

    def _check(auth: AuthContext = role_dep) -> AuthContext:
        return auth

    return _check


async def verify_internal_secret(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    """Authenticate /internal/* routes.

    Accepts the token bound to this tenant and host (nkz_platform_sdk.notify_auth)
    and, until NKZ_NOTIFY_ACCEPT_MASTER is false, the shared K8s secret itself.
    """
    if not verify_notification(
        request.headers,
        secret=settings.internal_service_secret,
        accept_master=accept_master_from_env(),
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing notification credentials",
        )
