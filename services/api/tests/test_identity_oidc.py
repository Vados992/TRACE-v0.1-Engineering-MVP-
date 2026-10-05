import base64
import json
import time

import pytest
from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15
from app.identity import IdentityError, OidcVerifier
from app.settings import settings


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def token(key, claims, kid="unit-test"):
    header = {"alg": "RS256", "kid": kid, "typ": "JWT"}
    head = b64url(json.dumps(header, separators=(",", ":")).encode())
    body = b64url(json.dumps(claims, separators=(",", ":")).encode())
    signing = f"{head}.{body}".encode()
    signature = pkcs1_15.new(key).sign(SHA256.new(signing))
    return f"{head}.{body}.{b64url(signature)}"


@pytest.mark.asyncio
async def test_oidc_verifies_signature_issuer_audience_and_mapped_role(monkeypatch):
    key = RSA.generate(2048)
    verifier = OidcVerifier()
    verifier._keys = {"unit-test": key.publickey()}
    verifier._expires_at = time.monotonic() + 60

    monkeypatch.setattr(settings, "oidc_issuer", "https://id.example/realms/trace")
    monkeypatch.setattr(settings, "oidc_audience", "trace-api")
    monkeypatch.setattr(settings, "oidc_subject_claim", "sub")
    monkeypatch.setattr(settings, "oidc_roles_claim", "groups")
    monkeypatch.setattr(
        settings,
        "oidc_role_map_json",
        json.dumps({"trace-analyst": "analyst", "trace-reviewer": "reviewer"}),
    )
    monkeypatch.setattr(settings, "oidc_clock_skew_seconds", 5)

    now = int(time.time())
    claims = {
        "iss": settings.oidc_issuer,
        "aud": settings.oidc_audience,
        "sub": "person-123",
        "iat": now,
        "exp": now + 300,
        "groups": ["unrelated-admin", "trace-reviewer"],
    }
    identity = await verifier.verify(token(key, claims))
    assert identity.subject == "person-123"
    assert identity.role == "reviewer"

    bad_audience = {**claims, "aud": "different-api"}
    with pytest.raises(IdentityError, match="audience"):
        await verifier.verify(token(key, bad_audience))


@pytest.mark.asyncio
async def test_oidc_rejects_unmapped_privilege(monkeypatch):
    key = RSA.generate(2048)
    verifier = OidcVerifier()
    verifier._keys = {"unit-test": key.publickey()}
    verifier._expires_at = time.monotonic() + 60

    monkeypatch.setattr(settings, "oidc_issuer", "https://id.example")
    monkeypatch.setattr(settings, "oidc_audience", "trace-api")
    monkeypatch.setattr(settings, "oidc_subject_claim", "sub")
    monkeypatch.setattr(settings, "oidc_roles_claim", "groups")
    monkeypatch.setattr(settings, "oidc_role_map_json", json.dumps({"trace-analyst": "analyst"}))

    now = int(time.time())
    claims = {
        "iss": settings.oidc_issuer,
        "aud": settings.oidc_audience,
        "sub": "person-456",
        "iat": now,
        "exp": now + 300,
        "groups": ["admin"],
    }
    with pytest.raises(IdentityError, match="no mapped TRACE role"):
        await verifier.verify(token(key, claims))
