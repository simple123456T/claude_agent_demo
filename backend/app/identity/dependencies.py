import logging
from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.identity.dev import get_dev_provider
from app.identity.oidc import (
    IdentityProviderUnavailable,
    JWKSKeyProvider,
    OIDCVerifier,
    TokenVerificationError,
)
from app.identity.service import CurrentUser, provision_user

logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache
def _build_verifier() -> OIDCVerifier:
    settings = get_settings()
    issuer = settings.oidc_issuer or ""
    return OIDCVerifier(
        issuer=issuer,
        audience=settings.effective_oidc_audience or "",
        key_provider=JWKSKeyProvider(
            issuer, settings.oidc_jwks_url, require_https=settings.is_production
        ),
        leeway_seconds=settings.oidc_clock_skew_seconds,
    )


def get_verifier(settings: Settings = Depends(get_settings)) -> OIDCVerifier:
    if settings.dev_auth_active:
        return get_dev_provider().verifier()
    # Fail closed: without an identity provider no protected endpoint is reachable.
    if not settings.oidc_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured (set OIDC_ISSUER and OIDC_AUDIENCE).",
        )
    return _build_verifier()


def get_request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    verifier: OIDCVerifier = Depends(get_verifier),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        identity = verifier.verify(credentials.credentials)
    except IdentityProviderUnavailable as exc:
        logger.warning("Identity provider unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Identity provider unavailable",
        ) from exc
    except TokenVerificationError as exc:
        logger.info("Rejected bearer token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from exc

    user = provision_user(
        db,
        identity,
        bootstrap_admin_subjects=settings.bootstrap_admin_subjects,
        request_id=get_request_id(request),
    )
    db.commit()
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")
    return CurrentUser.from_model(user)
