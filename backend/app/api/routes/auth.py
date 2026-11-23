import ipaddress

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.audit.service import record_event
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.identity.dependencies import get_request_id
from app.identity.dev import DEV_IDENTITIES, DEV_TOKEN_TTL_SECONDS, get_dev_provider

router = APIRouter(prefix="/auth", tags=["auth"])


class DevIdentityOut(BaseModel):
    subject: str
    label: str
    description: str


class AuthConfig(BaseModel):
    mode: str = Field(description="dev | oidc | unconfigured")
    dev_identities: list[DevIdentityOut] = []
    model_configured: bool = Field(
        default=False, description="Whether natural-language questions can be answered"
    )


class DevLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=64)


class DevLoginResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    subject: str


@router.get("/config", response_model=AuthConfig)
def auth_config(settings: Settings = Depends(get_settings)) -> AuthConfig:
    if settings.dev_auth_active:
        return AuthConfig(
            mode="dev",
            model_configured=settings.model_configured,
            dev_identities=[
                DevIdentityOut(subject=subject, label=label, description=description)
                for subject, label, description in DEV_IDENTITIES
            ],
        )
    return AuthConfig(
        mode="oidc" if settings.oidc_configured else "unconfigured",
        model_configured=settings.model_configured,
    )


@router.post("/dev-login", response_model=DevLoginResponse)
def dev_login(
    body: DevLoginRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> DevLoginResponse:
    # Indistinguishable from a missing route unless dev sign-in is deliberately active.
    if not settings.dev_auth_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    if not _is_loopback(request.client.host if request.client else None):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Local access only")
    if body.subject not in {subject for subject, _, _ in DEV_IDENTITIES}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unknown dev identity")

    record_event(
        db,
        action="auth.dev_login",
        actor_subject=body.subject,
        request_id=get_request_id(request),
    )
    db.commit()
    return DevLoginResponse(
        access_token=get_dev_provider().issue_token(body.subject),
        expires_in=DEV_TOKEN_TTL_SECONDS,
        subject=body.subject,
    )


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
