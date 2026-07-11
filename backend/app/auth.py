import os
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .database import get_db
from . import models

SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY or len(SECRET_KEY) < 32:
    raise ValueError(
        "SECRET_KEY environment variable is required and must be at least 32 characters. "
        "Generate one with: openssl rand -hex 32"
    )
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = int(os.getenv("ACCESS_TOKEN_EXPIRE_DAYS", "30"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: int, token_version: int = 0) -> str:
    expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(user_id), "exp": expire, "ver": token_version}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _get_user_from_token(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: Optional[str] = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        # Default 0 so tokens minted before AUDIT-29 (no "ver" claim) remain valid
        # against a freshly-migrated user row whose token_version also defaults to 0.
        token_version = payload.get("ver", 0)
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(
        models.User.id == int(user_id),
        models.User.is_active == True,
    ).first()
    if user is None:
        raise credentials_exception
    # Reject tokens whose version is stale (password changed since issue).
    if token_version != (user.token_version or 0):
        raise credentials_exception
    return user


def get_current_user(user: models.User = Depends(_get_user_from_token)) -> models.User:
    """Any authenticated, active user."""
    return user


def require_owner(user: models.User = Depends(_get_user_from_token)) -> models.User:
    """Restrict endpoint to users with the 'owner' role slug."""
    if user.role.name != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner role required",
        )
    return user


# ---------------------------------------------------------------------------
# Rate limiting (AUDIT-27) — dependency-free, in-process fixed-window limiter
# keyed on client IP. Blunts brute-force against unauthenticated auth endpoints
# without adding any new package. Single-process, in-memory, thread-locked; not
# distributed (fine for a single-container self-hosted app) and resets on restart.
# ---------------------------------------------------------------------------

_RATE_LIMIT_MAX = int(os.getenv("AUTH_RATE_LIMIT_MAX", "5"))
_RATE_LIMIT_WINDOW = int(os.getenv("AUTH_RATE_LIMIT_WINDOW_SECONDS", "60"))

# {(scope, client_ip): (window_start_epoch, count)}
_rate_buckets: dict[tuple[str, str], tuple[float, int]] = {}
_rate_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    """Best-effort client IP from the socket peer. Never trusts client headers."""
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def rate_limit(request: Request, scope: str) -> None:
    """Fixed-window rate limit. Raises 429 when the caller exceeds the limit for
    `scope` within the current window. Call at the top of an endpoint."""
    now = time.time()
    key = (scope, _client_ip(request))
    with _rate_lock:
        window_start, count = _rate_buckets.get(key, (now, 0))
        if now - window_start >= _RATE_LIMIT_WINDOW:
            window_start, count = now, 0
        count += 1
        _rate_buckets[key] = (window_start, count)
        if len(_rate_buckets) > 4096:
            for k, (ws, _) in list(_rate_buckets.items()):
                if now - ws >= _RATE_LIMIT_WINDOW:
                    _rate_buckets.pop(k, None)
        over = count > _RATE_LIMIT_MAX
    if over:
        retry_after = int(_RATE_LIMIT_WINDOW - (now - window_start))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please wait and try again.",
            headers={"Retry-After": str(max(retry_after, 1))},
        )


def reset_rate_limits() -> None:
    """Clear all rate-limit buckets. For tests and admin use only."""
    with _rate_lock:
        _rate_buckets.clear()
