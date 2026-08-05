"""initial documents table
Revision ID: 0001_initial_documents_table
Revises: 
Create Date: 2026-08-05 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0001_initial_documents_table'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'document',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('content_type', sa.String(), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('storage_path', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table('document')
