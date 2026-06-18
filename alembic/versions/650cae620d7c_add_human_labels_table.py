"""add_human_labels_table

Revision ID: 650cae620d7c
Revises: fab880fb6f0a
Create Date: 2026-01-31 22:23:45.643427

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '650cae620d7c'
down_revision: Union[str, Sequence[str], None] = 'fab880fb6f0a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('human_labels',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('fax_job_id', sa.Integer(), nullable=False),
        sa.Column('field_key', sa.String(), nullable=False),
        sa.Column('ai_value', sa.Text(), nullable=True),
        sa.Column('ai_confidence', sa.Float(), nullable=True),
        sa.Column('human_value', sa.Text(), nullable=True),
        sa.Column('human_action', sa.String(), nullable=True),
        sa.Column('review_time_seconds', sa.Float(), nullable=True),
        sa.Column('reviewer_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('page_number', sa.Integer(), nullable=True),
        sa.Column('bbox', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('human_labels')
