import base64
import hashlib
import hmac
import json

import jwt
import pytest
from cryptography.hazmat.primitives import serialization

from app.identity.oidc import (
    IdentityProviderUnavailable,
    JWKSKeyProvider,
    OIDCVerifier,
    StaticKeyProvider,
    TokenVerificationError,
)
from tests.tokens import AUDIENCE, ISSUER, generate_rsa_key, make_token


@pytest.fixture(scope="module")
def key():
    return generate_rsa_key()


@pytest.fixture(scope="module")
def verifier(key):
    return OIDCVerifier(
        issuer=ISSUER, audience=AUDIENCE, key_provider=StaticKeyProvider(key.public_key())
    )


def test_valid_token_yields_identity(key, verifier):
    token = make_token(
        key, "user-1", email="li@corp.internal", name="李雷", groups=["finance", 7]
    )

    identity = verifier.verify(token)

    assert identity.subject == "user-1"
    assert identity.issuer == ISSUER
    assert identity.email == "li@corp.internal"
    assert identity.name == "李雷"
    assert identity.groups == ("finance",)


@pytest.mark.parametrize(
    "overrides",
    [
        {"audience": "another-app"},
        {"issuer": "https://evil.example/realms/datagent"},
        {"expires_in": -600},
    ],
)
def test_rejects_wrong_audience_issuer_or_expired(key, verifier, overrides):
    with pytest.raises(TokenVerificationError):
        verifier.verify(make_token(key, "user-1", **overrides))


def test_rejects_token_signed_by_another_key(verifier):
    with pytest.raises(TokenVerificationError):
        verifier.verify(make_token(generate_rsa_key(), "user-1"))


def test_rejects_unsigned_token(verifier):
    def b64(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    token = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64({'sub': 'admin'})}."
    with pytest.raises(TokenVerificationError):
        verifier.verify(token)


def test_rejects_hmac_algorithm_confusion(key, verifier):
    """An attacker HMAC-signs with the public key as the secret (classic RS256/HS256 confusion).

    PyJWT refuses to produce such a token, so it is assembled by hand.
    """

    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64(
        json.dumps(
            {"iss": ISSUER, "aud": AUDIENCE, "sub": "admin", "iat": 0, "exp": 9999999999}
        ).encode()
    )
    signature = hmac.new(public_pem, f"{header}.{payload}".encode(), hashlib.sha256).digest()
    forged = f"{header}.{payload}.{b64(signature)}"

    with pytest.raises(TokenVerificationError):
        verifier.verify(forged)


def test_rejects_missing_subject(key, verifier):
    token = jwt.encode(
        {"iss": ISSUER, "aud": AUDIENCE, "iat": 0, "exp": 9999999999},
        key,
        algorithm="RS256",
    )
    with pytest.raises(TokenVerificationError):
        verifier.verify(token)


def test_rejects_garbage(verifier):
    with pytest.raises(TokenVerificationError):
        verifier.verify("not-a-jwt")


def test_jwks_provider_refuses_plain_http_when_https_required(key):
    provider = JWKSKeyProvider("http://sso.internal/realms/x", require_https=True)

    with pytest.raises(IdentityProviderUnavailable, match="scheme"):
        provider.get_signing_key(make_token(key, "user-1"))
