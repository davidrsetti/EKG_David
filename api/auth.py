"""
api/auth.py — JWT authentication and role extraction for the NEXUS API.
Every protected endpoint calls get_current_user() as a FastAPI dependency.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    import jwt
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False

from nexus.config.settings import settings

_bearer = HTTPBearer(auto_error=False)


@dataclass
class AuthenticatedUser:
    user_id:    str
    user_role:  str
    department: str
    email:      str
    is_agent:   bool = False      # True for AI agent service accounts
    agent_id:   str = ""
    clearance:  list[str] = None  # None = role defaults apply

    def __post_init__(self):
        if self.clearance is None:
            self.clearance = []


def create_token(
    user_id: str,
    user_role: str,
    department: str = "",
    email: str = "",
    is_agent: bool = False,
    agent_id: str = "",
    expires_minutes: int | None = None,
) -> str:
    """Create a signed JWT token for a user or agent."""
    if not JWT_AVAILABLE:
        raise RuntimeError("PyJWT not installed. Run: pip install pyjwt")

    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.security.token_expire_mins
    )
    payload = {
        "sub":        user_id,
        "role":       user_role,
        "dept":       department,
        "email":      email,
        "is_agent":   is_agent,
        "agent_id":   agent_id,
        "exp":        expire,
        "iss":        "nexus-platform",
    }
    return jwt.encode(payload, settings.security.jwt_secret, algorithm=settings.security.jwt_algorithm)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> AuthenticatedUser:
    """
    FastAPI dependency. Validates the Bearer JWT and returns the AuthenticatedUser.
    In development mode with no token, returns a default analyst user.
    """
    if credentials is None:
        if settings.is_production:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        # Dev fallback
        return AuthenticatedUser(user_id="dev-user", user_role="analyst", department="", email="dev@nexus.local")

    if not JWT_AVAILABLE:
        return AuthenticatedUser(user_id="no-jwt-lib", user_role="analyst", department="", email="")

    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.security.jwt_secret,
            algorithms=[settings.security.jwt_algorithm],
        )
        return AuthenticatedUser(
            user_id    = payload.get("sub", "unknown"),
            user_role  = payload.get("role", "viewer"),
            department = payload.get("dept", ""),
            email      = payload.get("email", ""),
            is_agent   = payload.get("is_agent", False),
            agent_id   = payload.get("agent_id", ""),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
        )


def require_role(*roles: str):
    """FastAPI dependency factory — restrict endpoint to specific roles."""
    async def _check(user: AuthenticatedUser = Depends(get_current_user)):
        if user.user_role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.user_role}' is not permitted for this endpoint.",
            )
        return user
    return _check
