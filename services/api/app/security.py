"""Small scoped API-key adapter. Replace with verified OIDC identities for institutions."""

import hashlib
import hmac
import json
from dataclasses import dataclass

from fastapi import HTTPException, Request
from fastapi.security import HTTPBearer

from .settings import settings

ROLES = {"analyst", "reviewer", "publisher", "admin"}
bearer_schema = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    subject: str
    role: str


def authenticate(header: str | None) -> Principal | None:
    if not header or not header.startswith("Bearer "):
        return None
    digest = hashlib.sha256(header[7:].encode()).hexdigest()
    for expected, identity in json.loads(settings.auth_keys_json).items():
        if hmac.compare_digest(digest, expected):
            if identity["role"] in ROLES:
                return Principal(identity["subject"], identity["role"])
    return None


def principal(request: Request) -> Principal:
    identity = getattr(request.state, "principal", None)
    if identity is None:
        raise HTTPException(401, "Bearer credential required")
    return identity


def require(request: Request, *roles: str) -> Principal:
    identity = principal(request)
    if identity.role not in roles:
        raise HTTPException(403, "Role does not permit this operation")
    return identity


def validate_configuration() -> None:
    keys = json.loads(settings.auth_keys_json)
    if not keys:
        raise ValueError("AUTH_KEYS_JSON must contain scoped credential hashes")
    identities = set()
    for digest, identity in keys.items():
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("AUTH_KEYS_JSON requires SHA-256 hex hashes")
        if identity.get("role") not in ROLES or not identity.get("subject"):
            raise ValueError("Invalid identity or role")
        if identity["subject"] in identities:
            raise ValueError("Use one role per identity; independent review needs distinct people")
        identities.add(identity["subject"])
    if settings.trace_env == "production":
        from .settings import DEV_KEYS

        if any(k in DEV_KEYS for k in keys):
            raise ValueError("Demo credentials are forbidden in production")
        if not settings.allowed_hosts or "*" in settings.allowed_hosts:
            raise ValueError("Production requires explicit ALLOWED_HOSTS")


def legacy_allowed(path: str, method: str, identity: Principal) -> bool:
    if method in {"GET", "HEAD"}:
        return True
    if path in {"/api/v1/graph/path", "/api/v1/resolve/compare", "/api/v1/investigations"}:
        return identity.role in {"analyst", "reviewer", "admin"}
    return identity.role in {"analyst", "admin"}
