import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.audit.service import record_event
from app.db.models import User
from app.identity.oidc import Identity

LOGIN_TOUCH_INTERVAL = timedelta(minutes=5)


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    issuer: str
    subject: str
    email: str | None
    display_name: str | None
    is_org_admin: bool

    @classmethod
    def from_model(cls, user: User) -> "CurrentUser":
        return cls(
            id=user.id,
            issuer=user.issuer,
            subject=user.subject,
            email=user.email,
            display_name=user.display_name,
            is_org_admin=user.is_org_admin,
        )


def ensure_user(db: Session, issuer: str, subject: str) -> tuple[User, bool]:
    """Return the user for (issuer, subject), creating a placeholder row if needed.

    Concurrency-safe: simultaneous first requests resolve to one row.
    """

    created_id = db.execute(
        pg_insert(User)
        .values(id=uuid.uuid4(), issuer=issuer, subject=subject)
        .on_conflict_do_nothing(index_elements=["issuer", "subject"])
        .returning(User.id)
    ).scalar_one_or_none()
    user = db.execute(
        select(User).where(User.issuer == issuer, User.subject == subject)
    ).scalar_one()
    return user, created_id is not None


def provision_user(
    db: Session,
    identity: Identity,
    *,
    bootstrap_admin_subjects: frozenset[str],
    request_id: str | None,
) -> User:
    """Sync the authenticated identity into the control plane (caller commits)."""

    user, created = ensure_user(db, identity.issuer, identity.subject)
    if created:
        record_event(
            db,
            action="user.provisioned",
            actor_user_id=user.id,
            actor_subject=user.subject,
            target_type="user",
            target_id=str(user.id),
            request_id=request_id,
        )

    if identity.email and user.email != identity.email:
        user.email = identity.email
    if identity.name and user.display_name != identity.name:
        user.display_name = identity.name

    if identity.subject in bootstrap_admin_subjects and not user.is_org_admin:
        user.is_org_admin = True
        record_event(
            db,
            action="user.org_admin.bootstrap_granted",
            actor_user_id=user.id,
            actor_subject=user.subject,
            target_type="user",
            target_id=str(user.id),
            request_id=request_id,
        )

    now = datetime.now(UTC)
    if user.last_login_at is None or now - user.last_login_at > LOGIN_TOUCH_INTERVAL:
        user.last_login_at = now
    return user
