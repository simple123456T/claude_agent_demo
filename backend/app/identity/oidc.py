import json
import logging
import threading
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit

import jwt

logger = logging.getLogger(__name__)

ALLOWED_ALGORITHMS = ("RS256", "RS384", "RS512", "ES256", "ES384", "PS256")


class TokenVerificationError(Exception):
    """The token is malformed, unsigned, expired or issued for someone else."""


class IdentityProviderUnavailable(Exception):
    """Signing keys could not be fetched from the identity provider."""


@dataclass(frozen=True)
class Identity:
    issuer: str
    subject: str
    email: str | None = None
    name: str | None = None
    groups: tuple[str, ...] = field(default_factory=tuple)


class SigningKeyProvider(Protocol):
    def get_signing_key(self, token: str) -> Any: ...


class StaticKeyProvider:
    """A fixed verification key; used by tests and IdPs with pinned keys."""

    def __init__(self, key: Any) -> None:
        self._key = key

    def get_signing_key(self, token: str) -> Any:
        return self._key


class JWKSKeyProvider:
    """Resolves keys from the IdP's JWKS endpoint, discovered lazily and cached."""

    def __init__(
        self,
        issuer: str,
        jwks_url: str | None = None,
        *,
        require_https: bool = True,
        timeout: float = 5.0,
    ) -> None:
        self._issuer = issuer
        self._jwks_url = jwks_url
        self._require_https = require_https
        self._timeout = timeout
        self._client: jwt.PyJWKClient | None = None
        self._lock = threading.Lock()

    def get_signing_key(self, token: str) -> Any:
        try:
            return self._get_client().get_signing_key_from_jwt(token).key
        except jwt.PyJWKClientConnectionError as exc:
            raise IdentityProviderUnavailable("JWKS endpoint unreachable") from exc
        except jwt.PyJWKClientError as exc:
            raise TokenVerificationError("No matching signing key") from exc

    def _get_client(self) -> jwt.PyJWKClient:
        with self._lock:
            if self._client is None:
                url = self._jwks_url or self._discover_jwks_url()
                self._check_url(url)
                self._client = jwt.PyJWKClient(
                    url, cache_keys=True, lifespan=300, timeout=int(self._timeout)
                )
            return self._client

    def _discover_jwks_url(self) -> str:
        discovery = self._issuer.rstrip("/") + "/.well-known/openid-configuration"
        self._check_url(discovery)
        try:
            with urllib.request.urlopen(discovery, timeout=self._timeout) as response:  # noqa: S310
                document = json.load(response)
        except (OSError, ValueError) as exc:
            raise IdentityProviderUnavailable("OIDC discovery failed") from exc
        if document.get("issuer") != self._issuer:
            raise IdentityProviderUnavailable("Discovery issuer does not match configuration")
        jwks_url = document.get("jwks_uri")
        if not isinstance(jwks_url, str):
            raise IdentityProviderUnavailable("Discovery document has no jwks_uri")
        # Do not follow a discovery document to an unrelated host.
        if urlsplit(jwks_url).hostname != urlsplit(self._issuer).hostname:
            raise IdentityProviderUnavailable("jwks_uri host differs from the issuer host")
        return jwks_url

    def _check_url(self, url: str) -> None:
        scheme = urlsplit(url).scheme
        allowed = {"https"} if self._require_https else {"https", "http"}
        if scheme not in allowed:
            raise IdentityProviderUnavailable(f"Refusing identity provider URL scheme {scheme!r}")


class OIDCVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        key_provider: SigningKeyProvider,
        leeway_seconds: int = 60,
        algorithms: tuple[str, ...] = ALLOWED_ALGORITHMS,
    ) -> None:
        self.issuer = issuer
        self.audience = audience
        self._key_provider = key_provider
        self._leeway = leeway_seconds
        self._algorithms = algorithms

    def verify(self, token: str) -> Identity:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise TokenVerificationError("Malformed token") from exc
        if header.get("alg") not in self._algorithms:
            raise TokenVerificationError("Token algorithm is not allowed")

        key = self._key_provider.get_signing_key(token)
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=list(self._algorithms),
                audience=self.audience,
                issuer=self.issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.InvalidTokenError as exc:
            raise TokenVerificationError(type(exc).__name__) from exc

        subject = claims["sub"]
        if not isinstance(subject, str) or not subject or len(subject) > 255:
            raise TokenVerificationError("Invalid subject claim")
        return Identity(
            issuer=self.issuer,
            subject=subject,
            email=_optional_str(claims.get("email"), 320),
            name=_optional_str(claims.get("name") or claims.get("preferred_username"), 200),
            groups=_groups(claims.get("groups")),
        )


def _optional_str(value: object, max_length: int) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()[:max_length]
    return None


def _groups(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))[:200]
