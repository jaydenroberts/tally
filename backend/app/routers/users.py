from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..auth import get_current_user, require_owner, hash_password

router = APIRouter(prefix="/api/users", tags=["users"])


# ---------------------------------------------------------------------------
# Current user
# ---------------------------------------------------------------------------

@router.get("/me", response_model=schemas.UserResponse)
def get_me(current_user: models.User = Depends(get_current_user)):
    return current_user


# ---------------------------------------------------------------------------
# User management (owner-only except self-service edits)
# ---------------------------------------------------------------------------

@router.get("", response_model=List[schemas.UserResponse])
def list_users(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    return db.query(models.User).all()


@router.post("", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: schemas.UserCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    if db.query(models.User).filter(models.User.username == payload.username).first():
        raise HTTPException(status_code=409, detail="Username already taken")

    role = db.query(models.Role).filter(models.Role.id == payload.role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    # Assign default persona based on role slug
    default_persona_name = "analyst" if role.name == "owner" else "family"
    default_persona = db.query(models.Persona).filter(
        models.Persona.name == default_persona_name
    ).first()

    user = models.User(
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role_id=payload.role_id,
        persona_id=default_persona.id if default_persona else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=schemas.UserResponse)
def update_user(
    user_id: int,
    payload: schemas.UserUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # Owners can edit anyone; regular users can only edit themselves (email/password only)
    if current_user.role.name != "owner" and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Not authorised")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.email is not None:
        user.email = payload.email
    if payload.password is not None:
        user.hashed_password = hash_password(payload.password)

    # Owner-only fields — use exclude_unset so null persona_id explicitly clears the field
    if current_user.role.name == "owner":
        explicitly_set = payload.model_dump(exclude_unset=True)
        if "role_id" in explicitly_set:
            role = db.query(models.Role).filter(models.Role.id == explicitly_set["role_id"]).first()
            if not role:
                raise HTTPException(status_code=404, detail="Role not found")
            user.role_id = explicitly_set["role_id"]
        if "persona_id" in explicitly_set:
            if explicitly_set["persona_id"] is not None:
                persona = db.query(models.Persona).filter(
                    models.Persona.id == explicitly_set["persona_id"]
                ).first()
                if not persona:
                    raise HTTPException(status_code=404, detail="Persona not found")
            user.persona_id = explicitly_set["persona_id"]  # allows explicit null to clear
        if "is_active" in explicitly_set:
            user.is_active = explicitly_set["is_active"]

    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_owner),
):
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()


# ---------------------------------------------------------------------------
# Roles (owner-only management)
# ---------------------------------------------------------------------------

@router.get("/roles", response_model=List[schemas.RoleResponse])
def list_roles(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    return db.query(models.Role).all()


@router.patch("/roles/{role_id}", response_model=schemas.RoleResponse)
def update_role(
    role_id: int,
    payload: schemas.RoleUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    role = db.query(models.Role).filter(models.Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if payload.display_name is not None:
        role.display_name = payload.display_name
    if payload.description is not None:
        role.description = payload.description
    db.commit()
    db.refresh(role)
    return role


# ---------------------------------------------------------------------------
# Personas (owner-only management; any user can read)
# ---------------------------------------------------------------------------

@router.get("/personas", response_model=List[schemas.PersonaResponse])
def list_personas(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    return db.query(models.Persona).all()


@router.post("/personas", response_model=schemas.PersonaResponse, status_code=status.HTTP_201_CREATED)
def create_persona(
    payload: schemas.PersonaCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_owner),
):
    if db.query(models.Persona).filter(models.Persona.name == payload.name).first():
        raise HTTPException(status_code=409, detail="A persona with that name already exists")
    persona = models.Persona(
        **payload.model_dump(),
        is_system=False,
        created_by=current_user.id,
    )
    db.add(persona)
    db.commit()
    db.refresh(persona)
    return persona


@router.patch("/personas/{persona_id}", response_model=schemas.PersonaResponse)
def update_persona(
    persona_id: int,
    payload: schemas.PersonaUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    persona = db.query(models.Persona).filter(models.Persona.id == persona_id).first()
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(persona, field, value)
    db.commit()
    db.refresh(persona)
    return persona


@router.delete("/personas/{persona_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_persona(
    persona_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    persona = db.query(models.Persona).filter(models.Persona.id == persona_id).first()
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    if persona.is_system:
        raise HTTPException(status_code=400, detail="System personas cannot be deleted")
    # Unassign from any users before deleting
    db.query(models.User).filter(models.User.persona_id == persona_id).update(
        {"persona_id": None}
    )
    db.delete(persona)
    db.commit()


# ---------------------------------------------------------------------------
# Persona Memory Files (owner-only management)
# ---------------------------------------------------------------------------

def _get_persona_or_404(persona_id: int, db: Session) -> models.Persona:
    persona = db.query(models.Persona).filter(models.Persona.id == persona_id).first()
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    return persona


@router.get(
    "/personas/{persona_id}/memory-files",
    response_model=List[schemas.PersonaMemoryFileResponse],
)
def list_memory_files(
    persona_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    _get_persona_or_404(persona_id, db)
    return (
        db.query(models.PersonaMemoryFile)
        .filter(models.PersonaMemoryFile.persona_id == persona_id)
        .order_by(models.PersonaMemoryFile.display_order)
        .all()
    )


@router.post(
    "/personas/{persona_id}/memory-files",
    response_model=schemas.PersonaMemoryFileResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_memory_file(
    persona_id: int,
    payload: schemas.PersonaMemoryFileCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    _get_persona_or_404(persona_id, db)
    mem_file = models.PersonaMemoryFile(
        persona_id=persona_id,
        **payload.model_dump(),
    )
    db.add(mem_file)
    db.commit()
    db.refresh(mem_file)
    return mem_file


@router.patch(
    "/personas/{persona_id}/memory-files/{file_id}",
    response_model=schemas.PersonaMemoryFileResponse,
)
def update_memory_file(
    persona_id: int,
    file_id: int,
    payload: schemas.PersonaMemoryFileUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    _get_persona_or_404(persona_id, db)
    mem_file = (
        db.query(models.PersonaMemoryFile)
        .filter(
            models.PersonaMemoryFile.id == file_id,
            models.PersonaMemoryFile.persona_id == persona_id,
        )
        .first()
    )
    if not mem_file:
        raise HTTPException(status_code=404, detail="Memory file not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(mem_file, field, value)
    db.commit()
    db.refresh(mem_file)
    return mem_file


@router.delete(
    "/personas/{persona_id}/memory-files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_memory_file(
    persona_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    _get_persona_or_404(persona_id, db)
    mem_file = (
        db.query(models.PersonaMemoryFile)
        .filter(
            models.PersonaMemoryFile.id == file_id,
            models.PersonaMemoryFile.persona_id == persona_id,
        )
        .first()
    )
    if not mem_file:
        raise HTTPException(status_code=404, detail="Memory file not found")
    db.delete(mem_file)
    db.commit()
