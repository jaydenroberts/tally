from fastapi import APIRouter, Depends, HTTPException, status
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
