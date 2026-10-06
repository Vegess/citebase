"""Auth & security primitives (security concerns #1, #5, #7).

- bcrypt password hashing (never store plaintext)
- JWT access tokens with expiry
- get_current_user dependency: every protected route resolves the user
  from the token, and org_id comes from the DB — never from the client.
"""
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models.models import User

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# Verified against when the email is unknown, so a failed login costs the same
# bcrypt time either way and response timing does not reveal which emails exist.
_DUMMY_HASH = pwd_context.hash("documind-timing-equaliser")


def verify_password_or_dummy(plain: str, hashed: str | None) -> bool:
    if hashed is None:
        pwd_context.verify(plain, _DUMMY_HASH)
        return False
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") not in {"HS256"}:
            raise JWTError("Rejected token algorithm")
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise credentials_error
        if payload.get("exp") is None:
            raise credentials_error
    except JWTError:
        raise credentials_error

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_error
    return user


# ---- Roles (RBAC) ----
# Ordered from least to most privileged. Checks compare ranks, so a new role
# slots in by position rather than by editing every route.
ROLES = ("VIEWER", "MEMBER", "ADMIN", "OWNER")
ROLE_RANK = {role: rank for rank, role in enumerate(ROLES)}


def role_rank(role: str) -> int:
    return ROLE_RANK.get(role, -1)


def require_role(min_role: str):
    """Dependency factory: the caller must hold at least `min_role`.

    The role is read from the database row behind the token, never from the
    token or the request, so a demoted user loses access immediately.
    """
    if min_role not in ROLE_RANK:
        raise ValueError(f"Unknown role: {min_role}")

    def dependency(user: User = Depends(get_current_user)) -> User:
        if role_rank(user.role) < ROLE_RANK[min_role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action needs the {min_role.lower()} role or higher.",
            )
        return user

    return dependency
