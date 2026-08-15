import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Protocol

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from pwdlib.exceptions import PwdlibError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from .database import get_session
from .models import Tenant, User, UserRole


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password: str, password_hash: str) -> bool: ...


class Argon2PasswordHasher:
    """Password hashing adapter kept separate from identity persistence."""

    def __init__(self) -> None:
        self._hasher = PasswordHash.recommended()

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        try:
            return self._hasher.verify(password, password_hash)
        except PwdlibError:
            return False


@dataclass(frozen=True)
class AuthSettings:
    signing_secret: str
    token_ttl_minutes: int

    @classmethod
    def from_environment(cls) -> "AuthSettings":
        secret = os.getenv("AUTH_TOKEN_SECRET", "")
        if len(secret) < 32:
            raise RuntimeError("AUTH_TOKEN_SECRET must contain at least 32 characters")
        ttl = int(os.getenv("AUTH_TOKEN_TTL_MINUTES", "30"))
        if ttl < 1 or ttl > 1440:
            raise RuntimeError("AUTH_TOKEN_TTL_MINUTES must be between 1 and 1440")
        return cls(signing_secret=secret, token_ttl_minutes=ttl)


class AccessTokenProvider(Protocol):
    def create(self, user: User) -> tuple[str, int]: ...

    def subject(self, token: str) -> str: ...


class JwtAccessTokenProvider:
    """Issues bounded HS256 tokens; current permissions are reloaded from the DB."""

    def __init__(self, settings: AuthSettings | None = None) -> None:
        self.settings = settings or AuthSettings.from_environment()

    def create(self, user: User) -> tuple[str, int]:
        now = datetime.now(UTC)
        lifetime = timedelta(minutes=self.settings.token_ttl_minutes)
        token = jwt.encode(
            {"sub": user.id, "iat": now, "exp": now + lifetime},
            self.settings.signing_secret,
            algorithm="HS256",
        )
        return token, int(lifetime.total_seconds())

    def subject(self, token: str) -> str:
        try:
            claims = jwt.decode(token, self.settings.signing_secret, algorithms=["HS256"])
            subject = claims.get("sub")
            if not isinstance(subject, str) or not subject:
                raise ValueError
            return subject
        except (jwt.PyJWTError, ValueError) as exc:
            raise HTTPException(status_code=401, detail="invalid_authentication") from exc


bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="invalid_authentication")
    user_id = JwtAccessTokenProvider().subject(credentials.credentials)
    result = await session.execute(select(User).where(User.id == user_id, User.is_active))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="invalid_authentication")
    return user


def require_roles(*roles: UserRole) -> Callable[..., Awaitable[User]]:
    """Build a centralized dependency for explicit route-level role policy."""

    async def dependency(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="insufficient_permissions")
        return user

    return dependency


async def bootstrap_local_admin(session: AsyncSession) -> None:
    """Create the opt-in local tenant admin without embedding credentials in code."""

    email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    slug = os.getenv("BOOTSTRAP_TENANT_SLUG", "local").strip().lower()
    name = os.getenv("BOOTSTRAP_TENANT_NAME", "Local workspace").strip()
    if not email and not password:
        return
    if not email or len(password) < 12 or not slug or not name:
        raise RuntimeError("Bootstrap admin configuration is incomplete or invalid")

    tenant_result = await session.execute(select(Tenant).where(Tenant.slug == slug))
    tenant = tenant_result.scalar_one_or_none()
    if tenant is None:
        tenant = Tenant(name=name, slug=slug)
        session.add(tenant)
        await session.flush()
    user_result = await session.execute(
        select(User).where(User.tenant_id == tenant.id, User.email == email)
    )
    if user_result.scalar_one_or_none() is None:
        session.add(
            User(
                tenant_id=tenant.id,
                email=email,
                password_hash=Argon2PasswordHasher().hash(password),
                role=UserRole.admin,
            )
        )
    await session.commit()
