"""add structured extraction results and provenance

Revision ID: 0004_structured_extraction
Revises: 0003_document_classification
Create Date: 2026-08-14 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_structured_extraction"
down_revision = "0003_document_classification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_structured_extraction",
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("document_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("extractor_version", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"], ["document.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("document_id"),
    )
    op.create_table(
        "document_structured_field",
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("field_name", sa.String(), nullable=False),
        sa.Column("value_index", sa.Integer(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("extraction_method", sa.String(), nullable=False),
        sa.Column("extractor_version", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "page_number > 0", name="ck_structured_field_page_positive"
        ),
        sa.CheckConstraint(
            "value_index >= 0", name="ck_structured_field_value_index_nonnegative"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document_structured_extraction.document_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("document_id", "field_name", "value_index"),
    )


def downgrade() -> None:
    op.drop_table("document_structured_field")
    op.drop_table("document_structured_extraction")
