"""Institutional OIDC verification for TRACE."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx
from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15

from .connectors.base import BaseConnector
from .settings import settings


class IdentityError(RuntimeError):
    pass


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except Exception as exc:
        raise IdentityError("Malformed JWT encoding") from exc


def _json_segment(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(_b64url_decode(value))
    except (ValueError, UnicodeDecodeError) as exc:
        raise IdentityError("Malformed JWT JSON") from exc
    if not isinstance(parsed, dict):
        raise IdentityError("JWT segment must be a JSON object")
    return parsed


def _audience_matches(actual: Any, expected: str) -> bool:
    if isinstance(actual, str):
        return actual == expected
    if isinstance(actual, list):
        return expected in actual
    return False


@dataclass(frozen=True)
class OidcIdentity:
    subject: str
    role: str
    issuer: str


class OidcVerifier:
    def __init__(self) -> None:
        self._keys: dict[str, RSA.RsaKey] = {}
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def _refresh(self) -> None:
        await BaseConnector.validate_url(settings.oidc_jwks_url)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.http_timeout_seconds),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.get(
                settings.oidc_jwks_url,
                headers={"Accept": "application/json"},
            )
            if response.is_redirect or response.status_code >= 400:
                raise IdentityError("OIDC JWKS endpoint unavailable")
            if len(response.content) > 1024 * 1024:
                raise IdentityError("OIDC JWKS response exceeds 1 MiB")
            payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
            raise IdentityError("OIDC JWKS schema invalid")
        keys: dict[str, RSA.RsaKey] = {}
        for jwk in payload["keys"]:
            if not isinstance(jwk, dict) or jwk.get("kty") != "RSA" or not jwk.get("kid"):
                continue
            if jwk.get("use") not in (None, "sig") or jwk.get("alg") not in (None, "RS256"):
                continue
            try:
                n = int.from_bytes(_b64url_decode(jwk["n"]), "big")
                e = int.from_bytes(_b64url_decode(jwk["e"]), "big")
                keys[str(jwk["kid"])] = RSA.construct((n, e))
            except (KeyError, ValueError, TypeError) as exc:
                raise IdentityError("OIDC JWKS contains an invalid RSA key") from exc
        if not keys:
            raise IdentityError("OIDC JWKS contains no usable RS256 signing keys")
        self._keys = keys
        self._expires_at = time.monotonic() + settings.oidc_jwks_cache_seconds

    async def _key(self, kid: str) -> RSA.RsaKey:
        if kid in self._keys and time.monotonic() < self._expires_at:
            return self._keys[kid]
        async with self._lock:
            if kid not in self._keys or time.monotonic() >= self._expires_at:
                await self._refresh()
        key = self._keys.get(kid)
        if key is None:
            async with self._lock:
                await self._refresh()
            key = self._keys.get(kid)
        if key is None:
            raise IdentityError("JWT signing key is not present in current JWKS")
        return key

    async def verify(self, token: str) -> OidcIdentity:
        try:
            encoded_header, encoded_payload, encoded_signature = token.split(".")
        except ValueError as exc:
            raise IdentityError("Malformed JWT") from exc
        header = _json_segment(encoded_header)
        claims = _json_segment(encoded_payload)
        if header.get("alg") != "RS256" or not header.get("kid"):
            raise IdentityError("Only keyed RS256 OIDC tokens are accepted")
        key = await self._key(str(header["kid"]))
        digest = SHA256.new(f"{encoded_header}.{encoded_payload}".encode("ascii"))
        try:
            pkcs1_15.new(key).verify(digest, _b64url_decode(encoded_signature))
        except (ValueError, TypeError) as exc:
            raise IdentityError("JWT signature verification failed") from exc

        now = int(time.time())
        leeway = settings.oidc_clock_skew_seconds
        if claims.get("iss") != settings.oidc_issuer:
            raise IdentityError("JWT issuer mismatch")
        if not _audience_matches(claims.get("aud"), settings.oidc_audience):
            raise IdentityError("JWT audience mismatch")
        try:
            exp = int(claims["exp"])
            iat = int(claims["iat"])
        except (KeyError, TypeError, ValueError) as exc:
            raise IdentityError("JWT exp and iat claims are required") from exc
        if exp < now - leeway:
            raise IdentityError("JWT expired")
        if iat > now + leeway:
            raise IdentityError("JWT issued-at time is in the future")
        if claims.get("nbf") is not None and int(claims["nbf"]) > now + leeway:
            raise IdentityError("JWT is not active yet")
        subject = str(claims.get(settings.oidc_subject_claim) or "").strip()
        if not subject:
            raise IdentityError("OIDC subject claim is missing")

        raw_roles = claims.get(settings.oidc_roles_claim, [])
        if isinstance(raw_roles, str):
            raw_roles = [raw_roles]
        if not isinstance(raw_roles, list):
            raise IdentityError("OIDC roles claim must be a string or array")
        mapping = json.loads(settings.oidc_role_map_json)
        mapped = {mapping.get(str(role)) for role in raw_roles}
        mapped.discard(None)
        order = ["analyst", "reviewer", "publisher", "admin"]
        role = next((candidate for candidate in reversed(order) if candidate in mapped), None)
        if role is None:
            raise IdentityError("OIDC identity has no mapped TRACE role")
        return OidcIdentity(subject=subject, role=role, issuer=settings.oidc_issuer)


oidc_verifier = OidcVerifier()
