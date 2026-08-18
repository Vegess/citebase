"""Auth routes: signup (creates org + user) and login (returns JWT)."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.models import Org, User
from app.models.schemas import SignupRequest, TokenResponse
from app.routes.chat import limiter

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute", key_func=get_remote_address)
def signup(request: Request, body: SignupRequest, db: Session = Depends(get_db)):
    existing = db.scalar(select(User).where(User.email == body.email))
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    org = db.scalar(select(Org).where(Org.name == body.org_name))
    if org is None:
        org = Org(name=body.org_name)
        db.add(org)
        db.flush()

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        org_id=org.id,
    )
    db.add(user)
    db.commit()

    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute", key_func=get_remote_address)
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == form.username))
    if user is None or not verify_password(form.password, user.hashed_password):
        # Same error either way — don't reveal which field was wrong
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    return TokenResponse(access_token=create_access_token(user.id))
