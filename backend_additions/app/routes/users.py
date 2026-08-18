"""Current-user route — powers the navbar and confirms a token is still valid.

Note the org name is resolved from the DB via the authenticated user, never
read from anything the client sent.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Org, User
from app.models.schemas import MeResponse

router = APIRouter(tags=["users"])


@router.get("/me", response_model=MeResponse)
def read_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    org = db.get(Org, user.org_id)
    return MeResponse(
        id=user.id,
        email=user.email,
        org_id=user.org_id,
        org_name=org.name if org else None,
    )
