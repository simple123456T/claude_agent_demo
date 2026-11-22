import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Workspace, WorkspaceMember
from app.identity.service import CurrentUser
from app.workspaces.permissions import WorkspaceRole, effective_permissions
from app.workspaces.schemas import WorkspaceSummary


def visible_workspaces(db: Session, user: CurrentUser) -> list[WorkspaceSummary]:
    """Workspaces the user is a member of; organization admins see all active ones."""

    membership = (
        select(WorkspaceMember.workspace_id, WorkspaceMember.role)
        .where(WorkspaceMember.user_id == user.id)
        .subquery()
    )
    query = (
        select(Workspace, membership.c.role)
        .outerjoin(membership, membership.c.workspace_id == Workspace.id)
        .where(Workspace.archived_at.is_(None))
        .order_by(Workspace.name, Workspace.slug)
    )
    if not user.is_org_admin:
        query = query.where(membership.c.role.is_not(None))

    summaries = []
    for workspace, role_value in db.execute(query):
        role = WorkspaceRole(role_value) if role_value else None
        summaries.append(
            WorkspaceSummary(
                id=workspace.id,
                slug=workspace.slug,
                name=workspace.name,
                role=role,
                permissions=sorted(effective_permissions(role, user.is_org_admin)),
            )
        )
    return summaries


def lock_workspace(db: Session, workspace_id: uuid.UUID) -> None:
    """Serialize membership changes in one workspace (prevents racing admin demotions)."""

    db.execute(select(Workspace.id).where(Workspace.id == workspace_id).with_for_update())


def other_admin_count(db: Session, workspace_id: uuid.UUID, excluding: uuid.UUID) -> int:
    return db.execute(
        select(func.count())
        .select_from(WorkspaceMember)
        .where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.role == WorkspaceRole.WORKSPACE_ADMIN.value,
            WorkspaceMember.user_id != excluding,
        )
    ).scalar_one()
