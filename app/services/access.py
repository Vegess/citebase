"""Who can see which documents.

Documents live in "General" (collection_id NULL, everyone) or in a collection.
A restricted collection is visible only to its members and to workspace
admins/owners; an open one to everyone. Every path that reads documents —
search, whole-document reading, the research agent, listings, passages,
verified answers — filters through `Scope`, so a restricted document can't
leak through a side door.

`Scope.collections` is None when nothing is restricted for this person (admin,
or no restricted collections exist), else the tuple of collection ids they may
see in addition to General.
"""
from dataclasses import dataclass

from sqlalchemy import or_, select, true
from sqlalchemy.orm import Session

from app.core.security import role_rank
from app.models.models import Collection, CollectionMember, Document, User


@dataclass(frozen=True)
class Scope:
    org_id: str
    collections: tuple[str, ...] | None


def scope_for(db: Session, user: User) -> Scope:
    if role_rank(user.role) >= role_rank("ADMIN"):
        return Scope(user.org_id, None)
    restricted = db.scalars(
        select(Collection.id).where(Collection.org_id == user.org_id, Collection.restricted.is_(True))
    ).all()
    if not restricted:
        return Scope(user.org_id, None)
    open_ids = db.scalars(
        select(Collection.id).where(Collection.org_id == user.org_id, Collection.restricted.is_(False))
    ).all()
    member_of = db.scalars(
        select(CollectionMember.collection_id).where(
            CollectionMember.user_id == user.id, CollectionMember.collection_id.in_(restricted))
    ).all()
    return Scope(user.org_id, tuple(sorted(set(open_ids) | set(member_of))))


def document_filter(collections: tuple[str, ...] | None):
    """SQLAlchemy condition on Document for the allowed collections (or True)."""
    if collections is None:
        return true()
    return or_(Document.collection_id.is_(None), Document.collection_id.in_(collections or ("",)))


def sql_filter(collections: tuple[str, ...] | None, alias: str = "d") -> tuple[str, dict]:
    """The same rule for hand-written SQL: (clause, params)."""
    if collections is None:
        return "", {}
    if not collections:
        return f"AND {alias}.collection_id IS NULL", {}
    return f"AND ({alias}.collection_id IS NULL OR {alias}.collection_id = ANY(:visible_collections))", {
        "visible_collections": list(collections)}


def can_see(scope: Scope, doc: Document | None) -> bool:
    return (
        doc is not None
        and doc.org_id == scope.org_id
        and (scope.collections is None or doc.collection_id is None or doc.collection_id in scope.collections)
    )


def can_use_collection(db: Session, user: User, collection_id: str | None) -> bool:
    if collection_id is None:
        return True
    col = db.get(Collection, collection_id)
    if col is None or col.org_id != user.org_id:
        return False
    scope = scope_for(db, user)
    return scope.collections is None or collection_id in scope.collections
