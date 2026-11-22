import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.workspaces.permissions import Permission, WorkspaceRole


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    slug: str = Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")
    name: str = Field(min_length=1, max_length=120)
    admin_subject: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="OIDC subject of the first workspace admin; defaults to the creator.",
    )


class WorkspaceSummary(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    role: WorkspaceRole | None
    permissions: list[Permission]


class MemberUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    subject: str = Field(min_length=1, max_length=255)
    role: WorkspaceRole


class MemberOut(BaseModel):
    user_id: uuid.UUID
    subject: str
    email: str | None
    display_name: str | None
    role: WorkspaceRole
    updated_at: datetime


class MeOut(BaseModel):
    id: uuid.UUID
    subject: str
    email: str | None
    display_name: str | None
    is_org_admin: bool
    workspaces: list[WorkspaceSummary]


class AuditEventOut(BaseModel):
    id: int
    occurred_at: datetime
    actor_user_id: uuid.UUID | None
    actor_subject: str | None
    action: str
    outcome: str
    target_type: str | None
    target_id: str | None
    request_id: str | None
    details: dict[str, Any]


class AuditPage(BaseModel):
    items: list[AuditEventOut]
    next_before_id: int | None
