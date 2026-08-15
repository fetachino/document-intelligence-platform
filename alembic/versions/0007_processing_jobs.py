"""add observable document processing jobs

Revision ID: 0007_processing_jobs
Revises: 0006_document_embeddings
Create Date: 2026-08-14 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_processing_jobs"
down_revision = "0006_document_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_processing_job",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("last_error_code", sa.String(), nullable=True),
        sa.Column("queued_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_processing_job_attempt_count"
        ),
        sa.CheckConstraint("max_attempts > 0", name="ck_processing_job_max_attempts"),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_document_processing_job_document_id"),
        "document_processing_job",
        ["document_id"],
    )
    op.create_index(
        "uq_processing_job_active_document",
        "document_processing_job",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_processing_job_active_document", table_name="document_processing_job"
    )
    op.drop_index(
        op.f("ix_document_processing_job_document_id"),
        table_name="document_processing_job",
    )
    op.drop_table("document_processing_job")
