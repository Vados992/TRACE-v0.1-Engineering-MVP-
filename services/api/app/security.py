"""Scoped API-key and institutional OIDC authentication."""

import hashlib
import hmac
import json
from dataclasses import dataclass

from fastapi import HTTPException, Request
from fastapi.security import HTTPBearer

from .identity import IdentityError, oidc_verifier
from .settings import DEV_KEYS, settings

ROLES = {"analyst", "reviewer", "publisher", "admin"}
bearer_schema = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    subject: str
    role: str
    auth_method: str = "api_key"


def authenticate(header: str | None) -> Principal | None:
    """Synchronous API-key authentication retained for development and tests."""
    if not header or not header.startswith("Bearer "):
        return None
    digest = hashlib.sha256(header[7:].encode()).hexdigest()
    for expected, identity in json.loads(settings.auth_keys_json).items():
        if hmac.compare_digest(digest, expected):
            if identity["role"] in ROLES:
                return Principal(identity["subject"], identity["role"], "api_key")
    return None


async def authenticate_request(header: str | None) -> Principal | None:
    if not header or not header.startswith("Bearer "):
        return None
    if settings.auth_mode in {"api_key", "hybrid"}:
        identity = authenticate(header)
        if identity is not None:
            return identity
    if settings.auth_mode in {"oidc", "hybrid"}:
        try:
            identity = await oidc_verifier.verify(header[7:])
            return Principal(identity.subject, identity.role, "oidc")
        except IdentityError:
            return None
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


def _validate_api_keys() -> None:
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
    if settings.trace_env == "production" and any(k in DEV_KEYS for k in keys):
        raise ValueError("Demo credentials are forbidden in production")


def _validate_oidc() -> None:
    if not settings.oidc_issuer.startswith("https://"):
        raise ValueError("OIDC_ISSUER must be an HTTPS issuer")
    if not settings.oidc_jwks_url.startswith("https://"):
        raise ValueError("OIDC_JWKS_URL must be HTTPS")
    if not settings.oidc_audience:
        raise ValueError("OIDC_AUDIENCE is required")
    mapping = json.loads(settings.oidc_role_map_json)
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("OIDC_ROLE_MAP_JSON must map external roles/groups to TRACE roles")
    if any(role not in ROLES for role in mapping.values()):
        raise ValueError("OIDC role map contains an unsupported TRACE role")


def validate_configuration() -> None:
    if settings.auth_mode in {"api_key", "hybrid"}:
        _validate_api_keys()
    if settings.auth_mode in {"oidc", "hybrid"}:
        _validate_oidc()
    if settings.trace_env == "production":
        if not settings.allowed_hosts or "*" in settings.allowed_hosts:
            raise ValueError("Production requires explicit ALLOWED_HOSTS")
        if settings.db_pool_min_size < 1 or settings.db_pool_max_size < settings.db_pool_min_size:
            raise ValueError("Invalid database pool bounds")
        if settings.db_statement_timeout_ms < 1000:
            raise ValueError("Production statement timeout is too low")


def legacy_allowed(path: str, method: str, identity: Principal) -> bool:
    if method in {"GET", "HEAD"}:
        return True
    if path in {"/api/v1/graph/path", "/api/v1/resolve/compare", "/api/v1/investigations"}:
        return identity.role in {"analyst", "reviewer", "admin"}
    return identity.role in {"analyst", "admin"}
