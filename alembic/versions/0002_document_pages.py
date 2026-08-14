"""add per-page extracted document text

Revision ID: 0002_document_pages
Revises: 0001_initial_documents_table
Create Date: 2026-08-14 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_document_pages"
down_revision = "0001_initial_documents_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_page",
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("extraction_method", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "page_number > 0", name="ck_document_page_number_positive"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["document.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("document_id", "page_number"),
    )


def downgrade() -> None:
    op.drop_table("document_page")
