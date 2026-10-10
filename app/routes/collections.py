"""Collections: folders of documents, optionally restricted to named members.

Anyone sees open collections; a restricted collection is visible to its
members and to admins/owners. Only admins create, change or delete them.
A collection with documents in it can't be deleted (moving restricted
documents to General would quietly expose them).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models.models import Collection, CollectionMember, Document, User
from app.services import access, audit, lifecycle

router = APIRouter(prefix="/collections", tags=["collections"])
require_admin = require_role("ADMIN")


class CollectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    restricted: bool = False
    member_ids: list[str] = []


class CollectionPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    restricted: bool | None = None
    member_ids: list[str] | None = None


def _out(db: Session, col: Collection, user: User, admin: bool) -> dict:
    members = db.scalars(select(CollectionMember.user_id).where(CollectionMember.collection_id == col.id)).all()
    count = db.scalar(select(func.count()).select_from(Document).where(
        Document.collection_id == col.id, Document.status != lifecycle.SUPERSEDED)) or 0
    out = {"id": col.id, "name": col.name, "description": col.description, "restricted": col.restricted,
           "documents": count, "is_member": user.id in members}
    if admin:
        out["member_ids"] = list(members)
    return out


def _set_members(db: Session, actor: User, col: Collection, member_ids: list[str]) -> None:
    valid = set(db.scalars(select(User.id).where(User.org_id == actor.org_id, User.id.in_(member_ids or [""]))))
    if set(member_ids) - valid:
        raise HTTPException(status_code=400, detail="Some of those people aren't in this workspace.")
    db.execute(delete(CollectionMember).where(CollectionMember.collection_id == col.id))
    for uid in valid:
        db.add(CollectionMember(collection_id=col.id, user_id=uid, added_at=datetime.now(timezone.utc)))


def _get(db: Session, actor: User, collection_id: str) -> Collection:
    col = db.get(Collection, collection_id)
    if col is None or col.org_id != actor.org_id:
        raise HTTPException(status_code=404, detail="Collection not found")
    return col


@router.get("")
def list_collections(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    scope = access.scope_for(db, user)
    admin = scope.collections is None and user.role in ("ADMIN", "OWNER")
    cols = db.scalars(select(Collection).where(Collection.org_id == user.org_id).order_by(Collection.name)).all()
    visible = [c for c in cols if scope.collections is None or c.id in scope.collections]
    general = db.scalar(select(func.count()).select_from(Document).where(
        Document.org_id == user.org_id, Document.collection_id.is_(None), Document.status != lifecycle.SUPERSEDED)) or 0
    return {"general_documents": general, "collections": [_out(db, c, user, admin) for c in visible]}


@router.post("", status_code=201)
def create_collection(body: CollectionIn, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    col = Collection(org_id=user.org_id, name=body.name.strip(), description=(body.description or "").strip() or None,
                     restricted=body.restricted, created_by=user.id, created_at=datetime.now(timezone.utc))
    db.add(col)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A collection with that name already exists.")
    _set_members(db, user, col, body.member_ids)
    audit.record(db, org_id=user.org_id, actor_id=user.id, action="collection.created", target_type="collection",
                 target_id=col.id, details={"name": col.name, "restricted": col.restricted})
    db.commit()
    return _out(db, col, user, True)


@router.patch("/{collection_id}")
def update_collection(collection_id: str, body: CollectionPatch, user: User = Depends(require_admin),
                      db: Session = Depends(get_db)):
    col = _get(db, user, collection_id)
    if body.name is not None:
        col.name = body.name.strip()
    if body.description is not None:
        col.description = body.description.strip() or None
    if body.restricted is not None:
        col.restricted = body.restricted
    if body.member_ids is not None:
        _set_members(db, user, col, body.member_ids)
    audit.record(db, org_id=user.org_id, actor_id=user.id, action="collection.updated", target_type="collection",
                 target_id=col.id, details={"name": col.name, "restricted": col.restricted})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A collection with that name already exists.")
    return _out(db, col, user, True)


@router.delete("/{collection_id}", status_code=204)
def delete_collection(collection_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    col = _get(db, user, collection_id)
    if db.scalar(select(func.count()).select_from(Document).where(Document.collection_id == col.id)):
        raise HTTPException(status_code=409, detail="Move or delete the documents in this collection first.")
    db.execute(delete(CollectionMember).where(CollectionMember.collection_id == col.id))
    audit.record(db, org_id=user.org_id, actor_id=user.id, action="collection.deleted", target_type="collection",
                 target_id=col.id, details={"name": col.name})
    db.delete(col)
    db.commit()
