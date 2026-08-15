import pytest

from backend.app.auth import get_current_user
from backend.app.main import app
from backend.app.models import LEGACY_TENANT_ID, User, UserRole


@pytest.fixture(autouse=True)
def authenticated_admin():
    """Keep legacy route tests focused while dedicated tests exercise real auth."""

    async def override_current_user() -> User:
        return User(
            id="local-reviewer",
            tenant_id=LEGACY_TENANT_ID,
            email="test-admin@example.test",
            password_hash="not-used-by-override",
            role=UserRole.admin,
        )

    app.dependency_overrides[get_current_user] = override_current_user
    yield
    app.dependency_overrides.pop(get_current_user, None)
