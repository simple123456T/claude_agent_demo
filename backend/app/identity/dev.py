"""Local-development identity provider.

Signs short-lived tokens with an in-memory key so the browser UI can be used before a real
OIDC provider is wired in. Never active in production, never reachable from another host,
and switched off automatically as soon as OIDC_ISSUER is configured.
"""

import threading
import time
import uuid
from functools import lru_cache

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from app.identity.oidc import OIDCVerifier, StaticKeyProvider

DEV_ISSUER = "datagent-dev-local"
DEV_AUDIENCE = "datagent-dev"
DEV_TOKEN_TTL_SECONDS = 8 * 3600

# Identities created by `python -m app.demo.seed`; the label is shown on the login screen.
DEV_IDENTITIES = (
    ("dev-admin", "管理员", "组织管理员 + 演示工作区管理员，可提问、管理成员、查看审计"),
    ("dev-analyst", "分析师", "演示工作区分析师，可提问、导出"),
    ("dev-viewer", "查看者", "演示工作区查看者，只读，不能提问"),
)


class DevIdentityProvider:
    def __init__(self) -> None:
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def issue_token(self, subject: str) -> str:
        now = int(time.time())
        return jwt.encode(
            {
                "iss": DEV_ISSUER,
                "aud": DEV_AUDIENCE,
                "sub": subject,
                "iat": now,
                "exp": now + DEV_TOKEN_TTL_SECONDS,
                "jti": uuid.uuid4().hex,
            },
            self._key,
            algorithm="RS256",
        )

    def verifier(self) -> OIDCVerifier:
        return OIDCVerifier(
            issuer=DEV_ISSUER,
            audience=DEV_AUDIENCE,
            key_provider=StaticKeyProvider(self._key.public_key()),
        )


_lock = threading.Lock()


@lru_cache
def get_dev_provider() -> DevIdentityProvider:
    with _lock:
        return DevIdentityProvider()
