"""Add total_pages and processed_pages columns

Revision ID: fab880fb6f0a
Revises: 97b091408aad
Create Date: 2026-01-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fab880fb6f0a'
down_revision: Union[str, Sequence[str], None] = '97b091408aad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add total_pages and processed_pages columns to fax_jobs table
    op.add_column('fax_jobs', sa.Column('total_pages', sa.Integer(), nullable=True, default=0))
    op.add_column('fax_jobs', sa.Column('processed_pages', sa.Integer(), nullable=True, default=0))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove the columns
    op.drop_column('fax_jobs', 'processed_pages')
    op.drop_column('fax_jobs', 'total_pages')