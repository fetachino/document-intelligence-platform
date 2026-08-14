"""add structured field correction audit history

Revision ID: 0005_structured_field_review
Revises: 0004_structured_extraction
Create Date: 2026-08-14 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_structured_field_review"
down_revision = "0004_structured_extraction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_structured_field_correction",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("field_name", sa.String(), nullable=False),
        sa.Column("value_index", sa.Integer(), nullable=False),
        sa.Column("automatic_value", sa.Text(), nullable=False),
        sa.Column("previous_effective_value", sa.Text(), nullable=False),
        sa.Column("corrected_value", sa.Text(), nullable=False),
        sa.Column("reviewer_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "value_index >= 0",
            name="ck_structured_field_correction_value_index_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document_structured_extraction.document_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_document_structured_field_correction_document_id"),
        "document_structured_field_correction",
        ["document_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_document_structured_field_correction_document_id"),
        table_name="document_structured_field_correction",
    )
    op.drop_table("document_structured_field_correction")
