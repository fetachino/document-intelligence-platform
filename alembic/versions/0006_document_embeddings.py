"""add document chunks and pgvector embeddings

Revision ID: 0006_document_embeddings
Revises: 0005_structured_field_review
Create Date: 2026-08-14 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0006_document_embeddings"
down_revision = "0005_structured_field_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "document_chunk",
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(128), nullable=False),
        sa.Column("embedding_model", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "page_number > 0", name="ck_document_chunk_page_positive"
        ),
        sa.CheckConstraint(
            "chunk_index >= 0", name="ck_document_chunk_index_nonnegative"
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "page_number"],
            ["document_page.document_id", "document_page.page_number"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("document_id", "page_number", "chunk_index"),
    )
    op.create_index(
        "ix_document_chunk_embedding_hnsw",
        "document_chunk",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunk_embedding_hnsw", table_name="document_chunk")
    op.drop_table("document_chunk")
