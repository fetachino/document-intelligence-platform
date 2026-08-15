import asyncio
from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient
from sqlmodel import select

from backend.app.auth import Argon2PasswordHasher, get_current_user
from backend.app.database import get_sessionmaker, init_db
from backend.app.main import app
from backend.app.models import Document, Tenant, User, UserRole

TEST_SECRET = "test-auth-signing-secret-with-more-than-32-characters"


def test_argon2_password_hashing_does_not_store_plaintext() -> None:
    hasher = Argon2PasswordHasher()
    password_hash = hasher.hash("correct horse battery staple")

    assert password_hash != "correct horse battery staple"
    assert hasher.verify("correct horse battery staple", password_hash)
    assert not hasher.verify("wrong password", password_hash)


def test_login_identity_roles_and_tenant_isolation(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
    monkeypatch.setenv("AUTH_TOKEN_SECRET", TEST_SECRET)
    asyncio.run(init_db())
    ids = asyncio.run(_seed_auth_data())
    app.dependency_overrides.pop(get_current_user, None)

    client = TestClient(app)
    failed = client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "alpha", "email": "admin@alpha.test", "password": "bad"},
    )
    assert failed.status_code == 401
    assert failed.json() == {"detail": "invalid_authentication"}

    admin_token = _login(client, "alpha", "admin@alpha.test", "admin-password")
    viewer_token = _login(client, "alpha", "viewer@alpha.test", "viewer-password")
    reviewer_token = _login(client, "alpha", "reviewer@alpha.test", "reviewer-password")

    me = client.get("/api/v1/auth/me", headers=_auth(admin_token))
    assert me.status_code == 200
    assert me.json()["tenant_slug"] == "alpha"
    assert me.json()["role"] == "admin"

    documents = client.get("/api/v1/documents/", headers=_auth(viewer_token))
    assert documents.status_code == 200
    assert [document["id"] for document in documents.json()] == [ids["alpha_document"]]

    cross_tenant = client.get(
        f"/api/v1/documents/{ids['beta_document']}/jobs", headers=_auth(admin_token)
    )
    assert cross_tenant.status_code == 404
    assert cross_tenant.json() == {"detail": "document_not_found"}

    assert client.post(
        f"/api/v1/documents/{ids['alpha_document']}/process",
        headers=_auth(viewer_token),
    ).status_code == 403
    assert client.patch(
        f"/api/v1/documents/{ids['alpha_document']}/classification",
        headers=_auth(viewer_token),
        json={"document_type": "invoice"},
    ).status_code == 403
    # Reviewer authorization succeeds before resource-state validation.
    assert client.patch(
        f"/api/v1/documents/{ids['alpha_document']}/classification",
        headers=_auth(reviewer_token),
        json={"document_type": "invoice"},
    ).status_code == 404

    assert client.get(
        f"/api/v1/search?q=invoice&document_id={ids['beta_document']}",
        headers=_auth(admin_token),
    ).status_code == 404
    assert client.post(
        "/api/v1/qa",
        headers=_auth(admin_token),
        json={"question": "What is the total?", "document_ids": [ids["beta_document"]]},
    ).status_code == 404


def test_missing_and_expired_tokens_are_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'expired.db'}")
    monkeypatch.setenv("AUTH_TOKEN_SECRET", TEST_SECRET)
    asyncio.run(init_db())
    asyncio.run(_seed_auth_data())
    app.dependency_overrides.pop(get_current_user, None)
    client = TestClient(app)

    assert client.get("/api/v1/auth/me").status_code == 401
    expired = jwt.encode(
        {
            "sub": "alpha-admin",
            "iat": datetime.now(UTC) - timedelta(hours=2),
            "exp": datetime.now(UTC) - timedelta(hours=1),
        },
        TEST_SECRET,
        algorithm="HS256",
    )
    response = client.get("/api/v1/auth/me", headers=_auth(expired))
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid_authentication"}


async def _seed_auth_data() -> dict[str, str]:
    hasher = Argon2PasswordHasher()
    async with get_sessionmaker()() as session:
        alpha = Tenant(id="alpha-tenant", name="Alpha", slug="alpha")
        beta = Tenant(id="beta-tenant", name="Beta", slug="beta")
        session.add_all([alpha, beta])
        session.add_all(
            [
                User(id="alpha-admin", tenant_id=alpha.id, email="admin@alpha.test", password_hash=hasher.hash("admin-password"), role=UserRole.admin),
                User(id="alpha-viewer", tenant_id=alpha.id, email="viewer@alpha.test", password_hash=hasher.hash("viewer-password"), role=UserRole.viewer),
                User(id="alpha-reviewer", tenant_id=alpha.id, email="reviewer@alpha.test", password_hash=hasher.hash("reviewer-password"), role=UserRole.reviewer),
            ]
        )
        alpha_document = Document(id="alpha-document", tenant_id=alpha.id, filename="alpha.pdf", content_type="application/pdf", size=1, storage_path="documents/alpha/source.pdf")
        beta_document = Document(id="beta-document", tenant_id=beta.id, filename="beta.pdf", content_type="application/pdf", size=1, storage_path="documents/beta/source.pdf")
        session.add_all([alpha_document, beta_document])
        await session.commit()
        result = await session.execute(select(User).where(User.id == "alpha-admin"))
        assert result.scalar_one().password_hash != "admin-password"
    return {"alpha_document": "alpha-document", "beta_document": "beta-document"}


def _login(client: TestClient, tenant: str, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": tenant, "email": email, "password": password},
    )
    assert response.status_code == 200
    return str(response.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
