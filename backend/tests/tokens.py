"""Helpers for signing test tokens with locally generated keys (no real IdP involved)."""

import time
import uuid
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "https://sso.test.internal/realms/datagent"
AUDIENCE = "datagent-api"


def generate_rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_token(
    private_key: Any,
    subject: str,
    *,
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    expires_in: int = 300,
    algorithm: str = "RS256",
    **claims: Any,
) -> str:
    now = int(time.time())
    payload = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "iat": now,
        "exp": now + expires_in,
        "jti": uuid.uuid4().hex,
        **claims,
    }
    return jwt.encode(payload, private_key, algorithm=algorithm, headers={"kid": "test"})
