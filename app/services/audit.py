"""Audit log writer. Callers add the event to their own session so it commits
(or rolls back) together with the change it describes."""
import json

from sqlalchemy.orm import Session

from app.models.models import AuditEvent


def record(
    db: Session,
    *,
    org_id: str,
    actor_id: str | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            org_id=org_id,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=json.dumps(details, sort_keys=True) if details else None,
        )
    )
