from enum import StrEnum


class WorkspaceRole(StrEnum):
    WORKSPACE_ADMIN = "workspace_admin"
    STEWARD = "steward"
    ANALYST = "analyst"
    VIEWER = "viewer"


class Permission(StrEnum):
    WORKSPACE_READ = "workspace:read"
    ASSET_READ = "asset:read"
    QUERY_RUN = "query:run"
    ASSET_WRITE = "asset:write"
    EXPORT_CREATE = "export:create"
    SEMANTIC_MANAGE = "semantic:manage"
    DATASOURCE_MANAGE = "datasource:manage"
    MEMBERS_MANAGE = "members:manage"
    AUDIT_READ = "audit:read"


_VIEWER = frozenset({Permission.WORKSPACE_READ, Permission.ASSET_READ})
_ANALYST = _VIEWER | {Permission.QUERY_RUN, Permission.ASSET_WRITE, Permission.EXPORT_CREATE}
_STEWARD = _ANALYST | {Permission.SEMANTIC_MANAGE}
_ADMIN = _STEWARD | {
    Permission.DATASOURCE_MANAGE,
    Permission.MEMBERS_MANAGE,
    Permission.AUDIT_READ,
}

ROLE_PERMISSIONS: dict[WorkspaceRole, frozenset[Permission]] = {
    WorkspaceRole.VIEWER: _VIEWER,
    WorkspaceRole.ANALYST: _ANALYST,
    WorkspaceRole.STEWARD: _STEWARD,
    WorkspaceRole.WORKSPACE_ADMIN: _ADMIN,
}

# Organization admins govern every workspace (membership and audit) but do not see
# workspace data unless they are also a member with a data role.
ORG_ADMIN_PERMISSIONS = frozenset(
    {Permission.WORKSPACE_READ, Permission.MEMBERS_MANAGE, Permission.AUDIT_READ}
)


def effective_permissions(role: WorkspaceRole | None, is_org_admin: bool) -> frozenset[Permission]:
    granted = ROLE_PERMISSIONS[role] if role is not None else frozenset()
    if is_org_admin:
        granted = granted | ORG_ADMIN_PERMISSIONS
    return granted
