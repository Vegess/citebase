"""Org administration: members, roles, invites, audit log.

Permission rules (enforced here, server-side, from the DB role):
- Any ADMIN or OWNER can list members, manage invites and read the audit log.
- You can only change or remove someone you outrank, and you can only grant a
  role below your own (OWNER may grant ADMIN). OWNER is never assignable here.
- Nobody can change or remove themselves, so an org cannot lose its owner.
"""
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_role, role_rank
from app.models.models import AuditEvent, OrgInvite, User
from app.models.schemas import AuditEventOut, InviteCreate, InviteCreated, InviteOut, MemberOut, RoleUpdate
from app.routes.auth import hash_invite_token, normalize_email
from app.services import audit

router = APIRouter(prefix="/org", tags=["org"])

INVITE_TTL = timedelta(days=7)
require_admin = require_role("ADMIN")


def _can_grant(actor: User, role: str) -> bool:
    return actor.role == "OWNER" or role_rank(role) < role_rank(actor.role)


def _member_or_404(db: Session, actor: User, user_id: str, *, lock: bool = False) -> User:
    query = select(User).where(User.id == user_id, User.org_id == actor.org_id)
    if lock:
        query = query.with_for_update()
    member = db.scalar(query)
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    return member


def _check_can_manage(actor: User, member: User) -> None:
    if member.id == actor.id:
        raise HTTPException(status_code=400, detail="You can't change your own role or remove yourself.")
    if role_rank(member.role) >= role_rank(actor.role):
        raise HTTPException(status_code=403, detail="You can only manage members below your own role.")


# ---- Members ----

@router.get("/members", response_model=list[MemberOut])
def list_members(actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.scalars(
        select(User).where(User.org_id == actor.org_id).order_by(User.created_at)
    ).all()


@router.patch("/members/{user_id}", response_model=MemberOut)
def change_role(user_id: str, body: RoleUpdate, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    member = _member_or_404(db, actor, user_id, lock=True)
    _check_can_manage(actor, member)
    if not _can_grant(actor, body.role):
        raise HTTPException(status_code=403, detail="You can't grant a role equal to or above your own.")

    old_role = member.role
    if old_role != body.role:
        member.role = body.role
        audit.record(
            db, org_id=actor.org_id, actor_id=actor.id, action="member.role_changed",
            target_type="user", target_id=member.id, details={"from": old_role, "to": body.role},
        )
    db.commit()
    db.refresh(member)
    return member


@router.delete("/members/{user_id}", status_code=204)
def remove_member(user_id: str, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Deactivate rather than delete: their uploads and history stay intact,
    and get_current_user rejects their existing tokens immediately."""
    member = _member_or_404(db, actor, user_id, lock=True)
    _check_can_manage(actor, member)
    if member.is_active:
        member.is_active = False
        audit.record(
            db, org_id=actor.org_id, actor_id=actor.id, action="member.removed",
            target_type="user", target_id=member.id, details={"email": member.email},
        )
    db.commit()


# ---- Invites ----

@router.post("/invites", response_model=InviteCreated, status_code=201)
def create_invite(body: InviteCreate, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    if not _can_grant(actor, body.role):
        raise HTTPException(status_code=403, detail="You can't invite someone at or above your own role.")

    email = normalize_email(body.email)
    if db.scalar(select(User.id).where(func.lower(User.email) == email)) is not None:
        raise HTTPException(status_code=409, detail="That email already has a DocuMind account.")

    now = datetime.now(timezone.utc)
    # One open invite per email per org: re-inviting replaces the old link.
    for stale in db.scalars(
        select(OrgInvite).where(
            OrgInvite.org_id == actor.org_id,
            OrgInvite.email == email,
            OrgInvite.accepted_at.is_(None),
            OrgInvite.revoked_at.is_(None),
        )
    ):
        stale.revoked_at = now

    token = secrets.token_urlsafe(32)
    invite = OrgInvite(
        org_id=actor.org_id,
        email=email,
        role=body.role,
        token_hash=hash_invite_token(token),
        invited_by=actor.id,
        expires_at=now + INVITE_TTL,
    )
    db.add(invite)
    db.flush()
    audit.record(
        db, org_id=actor.org_id, actor_id=actor.id, action="invite.created",
        target_type="invite", target_id=invite.id, details={"email": email, "role": body.role},
    )
    db.commit()
    db.refresh(invite)
    return InviteCreated(
        id=invite.id, email=invite.email, role=invite.role,
        created_at=invite.created_at, expires_at=invite.expires_at, token=token,
    )


@router.get("/invites", response_model=list[InviteOut])
def list_invites(actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    return db.scalars(
        select(OrgInvite)
        .where(
            OrgInvite.org_id == actor.org_id,
            OrgInvite.accepted_at.is_(None),
            OrgInvite.revoked_at.is_(None),
            OrgInvite.expires_at > now,
        )
        .order_by(OrgInvite.created_at.desc())
    ).all()


@router.delete("/invites/{invite_id}", status_code=204)
def revoke_invite(invite_id: str, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    invite = db.scalar(
        select(OrgInvite).where(OrgInvite.id == invite_id, OrgInvite.org_id == actor.org_id).with_for_update()
    )
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.accepted_at is not None:
        raise HTTPException(status_code=409, detail="This invite has already been accepted.")
    if invite.revoked_at is None:
        invite.revoked_at = datetime.now(timezone.utc)
        audit.record(
            db, org_id=actor.org_id, actor_id=actor.id, action="invite.revoked",
            target_type="invite", target_id=invite.id, details={"email": invite.email},
        )
    db.commit()


# ---- Audit log ----

@router.get("/audit", response_model=list[AuditEventOut])
def list_audit(limit: int = 50, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    limit = max(1, min(limit, 200))
    return db.scalars(
        select(AuditEvent)
        .where(AuditEvent.org_id == actor.org_id)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(limit)
    ).all()
