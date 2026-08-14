from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Field, SQLModel, col, select

from ..auth import Argon2PasswordHasher, JwtAccessTokenProvider, get_current_user
from ..database import get_session
from ..models import Tenant, User, UserRole

router = APIRouter()


class LoginRequest(SQLModel):
    tenant_slug: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class TokenResponse(SQLModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class CurrentUserResponse(SQLModel):
    id: str
    email: str
    role: UserRole
    tenant_id: str
    tenant_name: str
    tenant_slug: str


@router.post("/login")
async def login(
    request: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenResponse:
    result = await session.execute(
        select(User)
        .join(Tenant, col(Tenant.id) == col(User.tenant_id))
        .where(
            Tenant.slug == request.tenant_slug.strip().lower(),
            User.email == request.email.strip().lower(),
            User.is_active,
        )
    )
    user = result.scalar_one_or_none()
    if user is None or not Argon2PasswordHasher().verify(
        request.password, user.password_hash
    ):
        raise HTTPException(status_code=401, detail="invalid_authentication")
    token, expires_in = JwtAccessTokenProvider().create(user)
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.get("/me")
async def current_user(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CurrentUserResponse:
    tenant = await session.get(Tenant, user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=401, detail="invalid_authentication")
    return CurrentUserResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        tenant_slug=tenant.slug,
    )
