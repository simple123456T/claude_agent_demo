import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.service import record_denial, record_event
from app.db.models import AuditEvent, User, Workspace, WorkspaceMember
from app.db.session import get_db
from app.identity.dependencies import get_current_user, get_request_id
from app.identity.service import CurrentUser, ensure_user
from app.workspaces.dependencies import WorkspaceContext, require_workspace_permission
from app.workspaces.permissions import Permission, WorkspaceRole, effective_permissions
from app.workspaces.schemas import (
    AuditEventOut,
    AuditPage,
    MemberOut,
    MemberUpsert,
    WorkspaceCreate,
    WorkspaceSummary,
)
from app.workspaces.service import lock_workspace, other_admin_count, visible_workspaces

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceSummary])
def list_workspaces(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[WorkspaceSummary]:
    return visible_workspaces(db, user)


@router.post("", response_model=WorkspaceSummary, status_code=status.HTTP_201_CREATED)
def create_workspace(
    body: WorkspaceCreate,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceSummary:
    request_id = get_request_id(request)
    if not user.is_org_admin:
        record_denial(
            db,
            action="workspace.create",
            actor_user_id=user.id,
            actor_subject=user.subject,
            request_id=request_id,
            details={"slug": body.slug, "reason": "not_org_admin"},
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")

    admin_user: User | CurrentUser = user
    if body.admin_subject and body.admin_subject != user.subject:
        admin_user, _ = ensure_user(db, user.issuer, body.admin_subject)

    workspace = Workspace(slug=body.slug, name=body.name, created_by=user.id)
    db.add(workspace)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Workspace slug already exists"
        ) from exc

    db.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=admin_user.id,
            role=WorkspaceRole.WORKSPACE_ADMIN.value,
        )
    )
    record_event(
        db,
        action="workspace.create",
        actor_user_id=user.id,
        actor_subject=user.subject,
        workspace_id=workspace.id,
        target_type="workspace",
        target_id=str(workspace.id),
        request_id=request_id,
        details={"slug": workspace.slug, "admin_user_id": str(admin_user.id)},
    )
    db.commit()

    role = WorkspaceRole.WORKSPACE_ADMIN if admin_user.id == user.id else None
    return WorkspaceSummary(
        id=workspace.id,
        slug=workspace.slug,
        name=workspace.name,
        role=role,
        permissions=sorted(effective_permissions(role, user.is_org_admin)),
    )


@router.get("/{workspace_id}/members", response_model=list[MemberOut])
def list_members(
    ctx: WorkspaceContext = Depends(require_workspace_permission(Permission.WORKSPACE_READ)),
    db: Session = Depends(get_db),
) -> list[MemberOut]:
    rows = db.execute(
        select(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == ctx.workspace.id)
        .order_by(User.display_name, User.subject)
    )
    return [_member_out(member, user) for member, user in rows]


@router.put("/{workspace_id}/members", response_model=MemberOut)
def upsert_member(
    body: MemberUpsert,
    ctx: WorkspaceContext = Depends(require_workspace_permission(Permission.MEMBERS_MANAGE)),
    db: Session = Depends(get_db),
) -> MemberOut:
    workspace_id = ctx.workspace.id
    lock_workspace(db, workspace_id)
    target, _ = ensure_user(db, ctx.user.issuer, body.subject)

    previous_role = db.execute(
        select(WorkspaceMember.role).where(
            WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == target.id
        )
    ).scalar_one_or_none()
    demoting_admin = (
        previous_role == WorkspaceRole.WORKSPACE_ADMIN.value
        and body.role != WorkspaceRole.WORKSPACE_ADMIN
    )
    if demoting_admin and other_admin_count(db, workspace_id, excluding=target.id) == 0:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A workspace must keep at least one workspace admin",
        )

    now = datetime.now(UTC)
    db.execute(
        pg_insert(WorkspaceMember)
        .values(workspace_id=workspace_id, user_id=target.id, role=body.role.value)
        .on_conflict_do_update(
            index_elements=["workspace_id", "user_id"],
            set_={"role": body.role.value, "updated_at": now},
        )
    )
    record_event(
        db,
        action="workspace.member.upsert",
        actor_user_id=ctx.user.id,
        actor_subject=ctx.user.subject,
        workspace_id=workspace_id,
        target_type="user",
        target_id=str(target.id),
        request_id=ctx.request_id,
        details={"subject": target.subject, "previous_role": previous_role, "role": body.role},
    )
    db.commit()

    member = db.get(WorkspaceMember, (workspace_id, target.id))
    db.refresh(member)
    return _member_out(member, target)


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    user_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(require_workspace_permission(Permission.MEMBERS_MANAGE)),
    db: Session = Depends(get_db),
) -> Response:
    workspace_id = ctx.workspace.id
    lock_workspace(db, workspace_id)
    member = db.get(WorkspaceMember, (workspace_id, user_id))
    if member is None:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    if (
        member.role == WorkspaceRole.WORKSPACE_ADMIN.value
        and other_admin_count(db, workspace_id, excluding=user_id) == 0
    ):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A workspace must keep at least one workspace admin",
        )

    previous_role = member.role
    db.delete(member)
    record_event(
        db,
        action="workspace.member.remove",
        actor_user_id=ctx.user.id,
        actor_subject=ctx.user.subject,
        workspace_id=workspace_id,
        target_type="user",
        target_id=str(user_id),
        request_id=ctx.request_id,
        details={"previous_role": previous_role},
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{workspace_id}/audit-events", response_model=AuditPage)
def list_audit_events(
    limit: int = Query(default=50, ge=1, le=200),
    before_id: int | None = Query(default=None, ge=1),
    ctx: WorkspaceContext = Depends(require_workspace_permission(Permission.AUDIT_READ)),
    db: Session = Depends(get_db),
) -> AuditPage:
    query = select(AuditEvent).where(AuditEvent.workspace_id == ctx.workspace.id)
    if before_id is not None:
        query = query.where(AuditEvent.id < before_id)
    rows = list(db.execute(query.order_by(AuditEvent.id.desc()).limit(limit + 1)).scalars())

    # Reading the audit trail is itself an audited, privileged action.
    record_event(
        db,
        action="audit.read",
        actor_user_id=ctx.user.id,
        actor_subject=ctx.user.subject,
        workspace_id=ctx.workspace.id,
        target_type="workspace",
        target_id=str(ctx.workspace.id),
        request_id=ctx.request_id,
        details={"limit": limit, "before_id": before_id},
    )
    db.commit()

    page = rows[:limit]
    return AuditPage(
        items=[AuditEventOut.model_validate(row, from_attributes=True) for row in page],
        next_before_id=page[-1].id if len(rows) > limit else None,
    )


def _member_out(member: WorkspaceMember, user: User) -> MemberOut:
    return MemberOut(
        user_id=user.id,
        subject=user.subject,
        email=user.email,
        display_name=user.display_name,
        role=WorkspaceRole(member.role),
        updated_at=member.updated_at,
    )
