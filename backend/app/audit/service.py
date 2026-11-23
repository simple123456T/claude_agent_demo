import json
import logging
import uuid
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.db.models import AuditEvent

logger = logging.getLogger(__name__)

Outcome = Literal["success", "denied", "failure"]
MAX_DETAILS_BYTES = 4096


def record_event(
    db: Session,
    *,
    action: str,
    outcome: Outcome = "success",
    actor_user_id: uuid.UUID | None = None,
    actor_subject: str | None = None,
    workspace_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    request_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Add an audit row to the caller's transaction; it commits with the change it describes."""

    db.add(
        AuditEvent(
            action=action,
            outcome=outcome,
            actor_user_id=actor_user_id,
            actor_subject=actor_subject,
            workspace_id=workspace_id,
            target_type=target_type,
            target_id=target_id,
            request_id=request_id,
            details=_bounded(details or {}),
        )
    )


def record_isolated(db: Session, outcome: Outcome, **kwargs: Any) -> None:
    """Persist an event in its own transaction, because the request itself is about to fail."""

    try:
        with Session(bind=db.get_bind()) as audit_session:
            record_event(audit_session, outcome=outcome, **kwargs)
            audit_session.commit()
    except Exception:  # noqa: BLE001 - a broken audit write must not change the HTTP outcome
        logger.exception("Failed to persist %s audit event %s", outcome, kwargs.get("action"))


def record_denial(db: Session, **kwargs: Any) -> None:
    record_isolated(db, "denied", **kwargs)


def record_failure(db: Session, **kwargs: Any) -> None:
    record_isolated(db, "failure", **kwargs)


def _bounded(details: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(details, default=str, ensure_ascii=False)
    if len(encoded.encode("utf-8")) <= MAX_DETAILS_BYTES:
        return json.loads(encoded)
    return {"truncated": True, "keys": sorted(str(key) for key in details)[:50]}
