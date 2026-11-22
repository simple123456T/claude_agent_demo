import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record_denial
from app.db.models import Workspace, WorkspaceMember
from app.db.session import get_db
from app.identity.dependencies import get_current_user, get_request_id
from app.identity.service import CurrentUser
from app.workspaces.permissions import Permission, WorkspaceRole, effective_permissions


@dataclass(frozen=True)
class WorkspaceContext:
    workspace: Workspace
    user: CurrentUser
    role: WorkspaceRole | None
    permissions: frozenset[Permission]
    request_id: str | None


def require_workspace_permission(permission: Permission):
    """Resolve the caller's role in the path workspace and enforce one permission.

    Workspaces the caller cannot see answer 404, so their existence is not disclosed.
    Every refusal is audited.
    """

    def dependency(
        workspace_id: uuid.UUID,
        request: Request,
        user: CurrentUser = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> WorkspaceContext:
        request_id = get_request_id(request)
        workspace = db.get(Workspace, workspace_id)
        role_value = db.execute(
            select(WorkspaceMember.role).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user.id,
            )
        ).scalar_one_or_none()
        role = WorkspaceRole(role_value) if role_value else None
        permissions = effective_permissions(role, user.is_org_admin)

        audit = {
            "actor_user_id": user.id,
            "actor_subject": user.subject,
            "workspace_id": workspace_id,
            "action": f"authz.{permission.value}",
            "target_type": "workspace",
            "target_id": str(workspace_id),
            "request_id": request_id,
        }
        if workspace is None or workspace.archived_at is not None or not permissions:
            record_denial(db, details={"reason": "not_visible"}, **audit)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        if permission not in permissions:
            record_denial(db, details={"reason": "missing_permission", "role": role_value}, **audit)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
        return WorkspaceContext(workspace, user, role, permissions, request_id)

    return dependency
