import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..auth import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=schemas.Token)
def login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(
        models.User.username == payload.username,
        models.User.is_active == True,
    ).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    token = create_access_token(user.id)
    return schemas.Token(access_token=token, user=user)


@router.post("/setup", response_model=schemas.Token, status_code=status.HTTP_201_CREATED)
def first_run_setup(payload: schemas.UserCreate, db: Session = Depends(get_db)):
    """
    Create the first owner account. Only works when no users exist yet.
    Subsequent registrations must be done by an existing owner via /api/users.
    """
    if db.query(models.User).count() > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Setup already complete. Ask an owner to create your account.",
        )
    owner_role = db.query(models.Role).filter(models.Role.name == "owner").first()
    if not owner_role:
        raise HTTPException(status_code=500, detail="Owner role not found in database")

    user = models.User(
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role_id=owner_role.id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(user.id)
    return schemas.Token(access_token=token, user=user)


class RecoverRequest(BaseModel):
    token: str
    new_password: str


@router.post("/recover", status_code=status.HTTP_200_OK)
def recover_owner_password(payload: RecoverRequest, db: Session = Depends(get_db)):
    """
    Reset the first owner account's password using a pre-shared env var token.

    This endpoint is only active when the RECOVERY_TOKEN environment variable is
    set. Once recovery is complete, remove RECOVERY_TOKEN and restart the container
    to disable this endpoint.

    Security: token comparison uses secrets.compare_digest to prevent timing attacks.
    """
    recovery_token = os.getenv("RECOVERY_TOKEN")
    if not recovery_token:
        # Behave as if the route does not exist when the token is unset.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    # Constant-time comparison — prevents timing-based token enumeration.
    if not secrets.compare_digest(recovery_token, payload.token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid recovery token",
        )

    # Target: the owner-role account with the lowest ID (first owner created).
    owner_role = db.query(models.Role).filter(models.Role.name == "owner").first()
    if not owner_role:
        raise HTTPException(status_code=500, detail="Owner role not found in database")

    owner = (
        db.query(models.User)
        .filter(models.User.role_id == owner_role.id)
        .order_by(models.User.id.asc())
        .first()
    )
    if not owner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No owner account found",
        )

    owner.hashed_password = hash_password(payload.new_password)
    db.commit()

    return {"detail": f"Password reset for owner account '{owner.username}'. Remove RECOVERY_TOKEN and restart."}
