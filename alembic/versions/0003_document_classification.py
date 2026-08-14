"""add document classification and correction history

Revision ID: 0003_document_classification
Revises: 0002_document_pages
Create Date: 2026-08-14 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_document_classification"
down_revision = "0002_document_pages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_classification",
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("predicted_type", sa.String(), nullable=False),
        sa.Column("effective_type", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("classifier_version", sa.String(), nullable=False),
        sa.Column("classified_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"], ["document.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("document_id"),
    )
    op.create_table(
        "document_classification_review",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("previous_type", sa.String(), nullable=False),
        sa.Column("corrected_type", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"], ["document.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_document_classification_review_document_id",
        "document_classification_review",
        ["document_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_classification_review_document_id",
        table_name="document_classification_review",
    )
    op.drop_table("document_classification_review")
    op.drop_table("document_classification")
