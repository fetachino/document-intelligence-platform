"""add local identities, tenant ownership, and basic roles

Revision ID: 0008_auth_tenant_rbac
Revises: 0007_processing_jobs
Create Date: 2026-08-14 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_auth_tenant_rbac"
down_revision = "0007_processing_jobs"
branch_labels = None
depends_on = None

LEGACY_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.create_table(
        "tenant",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tenant_slug"), "tenant", ["slug"], unique=True)
    op.create_table(
        "app_user",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_app_user_email"), "app_user", ["email"])
    op.create_index(op.f("ix_app_user_tenant_id"), "app_user", ["tenant_id"])
    op.create_index(
        "uq_app_user_tenant_email",
        "app_user",
        ["tenant_id", "email"],
        unique=True,
    )

    # Existing development documents remain accessible in an explicit legacy tenant.
    op.execute(
        sa.text(
            "INSERT INTO tenant (id, name, slug, created_at) "
            "VALUES (:id, 'Legacy workspace', 'legacy', CURRENT_TIMESTAMP)"
        ).bindparams(id=LEGACY_TENANT_ID)
    )
    op.add_column("document", sa.Column("tenant_id", sa.String(), nullable=True))
    op.execute(
        sa.text("UPDATE document SET tenant_id = :id WHERE tenant_id IS NULL").bindparams(
            id=LEGACY_TENANT_ID
        )
    )
    op.alter_column("document", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_document_tenant_id_tenant", "document", "tenant", ["tenant_id"], ["id"]
    )
    op.create_index(op.f("ix_document_tenant_id"), "document", ["tenant_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_document_tenant_id"), table_name="document")
    op.drop_constraint(
        "fk_document_tenant_id_tenant", "document", type_="foreignkey"
    )
    op.drop_column("document", "tenant_id")
    op.drop_index("uq_app_user_tenant_email", table_name="app_user")
    op.drop_index(op.f("ix_app_user_tenant_id"), table_name="app_user")
    op.drop_index(op.f("ix_app_user_email"), table_name="app_user")
    op.drop_table("app_user")
    op.drop_index(op.f("ix_tenant_slug"), table_name="tenant")
    op.drop_table("tenant")
