"""
routers/chat_sessions.py — persistent chat session management (BACKLOG-016).

Endpoints:
    GET    /api/chat/sessions          — list sessions for (user, persona)
    POST   /api/chat/sessions          — create an empty session (rare; POST /api/chat
                                         usually creates one implicitly)
    GET    /api/chat/sessions/{id}     — session + ordered messages (cursor-paginated)
    DELETE /api/chat/sessions/{id}     — hard delete (messages cascade)

Cross-cutting 404 invariant: every endpoint that takes a session id resolves it
with ONE filtered query (id AND user_id AND persona_id) — never fetch-then-check,
so another user's id and another persona's id are indistinguishable from a
nonexistent id in both body and timing. POST /api/chat (routers/chat.py) reuses
get_owned_session() for the same guarantee.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..auth import get_current_user
from ..providers import AI_PROVIDER

router = APIRouter(prefix="/api/chat/sessions", tags=["chat-sessions"])

# Identical body on every ownership/persona miss — do not specialise per cause.
SESSION_NOT_FOUND = "Session not found"

# GET /{id} returns at most this many messages per page.
MESSAGE_PAGE_CAP = 500


def get_owned_session(
    session_id: int,
    db: Session,
    current_user: models.User,
) -> models.ChatSession:
    """
    Resolve a session id to a ChatSession owned by (current_user, current persona)
    in a single filtered query. Raises an identical 404 for nonexistent ids,
    other users' ids, and other personas' ids (no timing/shape leak).
    """
    session = (
        db.query(models.ChatSession)
        .filter(
            models.ChatSession.id == session_id,
            models.ChatSession.user_id == current_user.id,
            models.ChatSession.persona_id == current_user.persona_id,
        )
        .first()
    )
    if session is None:
        raise HTTPException(status_code=404, detail=SESSION_NOT_FOUND)
    return session


@router.get("", response_model=schemas.ChatSessionListResponse)
def list_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """List chat sessions for the current (user, persona), newest first."""
    sessions = (
        db.query(models.ChatSession)
        .filter(
            models.ChatSession.user_id == current_user.id,
            models.ChatSession.persona_id == current_user.persona_id,
        )
        .order_by(models.ChatSession.updated_at.desc(), models.ChatSession.id.desc())
        .limit(limit)
        .all()
    )
    return {"sessions": sessions, "provider": AI_PROVIDER}


@router.post("", response_model=schemas.ChatSessionSummary, status_code=201)
def create_session(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Create an empty session (provider stamped from the active AI_PROVIDER)."""
    if current_user.persona_id is None:
        raise HTTPException(
            status_code=400,
            detail="No persona assigned to this user. Assign a persona in Settings before using the chat.",
        )
    session = models.ChatSession(
        user_id=current_user.id,
        persona_id=current_user.persona_id,
        provider=AI_PROVIDER,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/{session_id}", response_model=schemas.ChatSessionDetailResponse)
def get_session(
    session_id: int,
    before_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Session + ordered messages, capped at the 500 most recent. Pass
    ?before_id=<oldest returned id> to page backwards through older history.
    """
    session = get_owned_session(session_id, db, current_user)

    q = db.query(models.ChatMessage).filter(
        models.ChatMessage.session_id == session.id,
    )
    if before_id is not None:
        q = q.filter(models.ChatMessage.id < before_id)

    # Fetch the most recent page in DESC order, then flip to ASC for display.
    page = (
        q.order_by(models.ChatMessage.id.desc())
        .limit(MESSAGE_PAGE_CAP + 1)
        .all()
    )
    has_more = len(page) > MESSAGE_PAGE_CAP
    messages = list(reversed(page[:MESSAGE_PAGE_CAP]))

    return {
        "id": session.id,
        "title": session.title,
        "provider": session.provider,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "messages": messages,
        "has_more": has_more,
    }


@router.delete("/{session_id}", status_code=204)
def delete_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Hard delete a session; messages are removed by cascade."""
    session = get_owned_session(session_id, db, current_user)
    db.delete(session)
    db.commit()
    return None
