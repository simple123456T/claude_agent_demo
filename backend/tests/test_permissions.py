import pytest

from app.workspaces.permissions import (
    ORG_ADMIN_PERMISSIONS,
    Permission,
    WorkspaceRole,
    effective_permissions,
)


def test_roles_are_strictly_increasing():
    order = [
        WorkspaceRole.VIEWER,
        WorkspaceRole.ANALYST,
        WorkspaceRole.STEWARD,
        WorkspaceRole.WORKSPACE_ADMIN,
    ]
    granted = [effective_permissions(role, False) for role in order]

    for lower, higher in zip(granted, granted[1:], strict=False):
        assert lower < higher


@pytest.mark.parametrize(
    ("role", "allowed", "denied"),
    [
        (WorkspaceRole.VIEWER, Permission.ASSET_READ, Permission.QUERY_RUN),
        (WorkspaceRole.ANALYST, Permission.QUERY_RUN, Permission.SEMANTIC_MANAGE),
        (WorkspaceRole.STEWARD, Permission.SEMANTIC_MANAGE, Permission.MEMBERS_MANAGE),
        (WorkspaceRole.WORKSPACE_ADMIN, Permission.AUDIT_READ, None),
    ],
)
def test_role_boundaries(role, allowed, denied):
    permissions = effective_permissions(role, is_org_admin=False)

    assert allowed in permissions
    if denied is not None:
        assert denied not in permissions


def test_non_member_has_no_permissions():
    assert effective_permissions(None, is_org_admin=False) == frozenset()


def test_org_admin_governs_without_seeing_workspace_data():
    permissions = effective_permissions(None, is_org_admin=True)

    assert permissions == ORG_ADMIN_PERMISSIONS
    assert Permission.QUERY_RUN not in permissions
    assert Permission.ASSET_READ not in permissions
