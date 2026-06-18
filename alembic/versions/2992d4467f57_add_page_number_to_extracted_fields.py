"""add_page_number_to_extracted_fields

Revision ID: 2992d4467f57
Revises: 650cae620d7c
Create Date: 2026-01-31 23:18:41.372931

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2992d4467f57'
down_revision: Union[str, Sequence[str], None] = '650cae620d7c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('fax_extracted_fields', sa.Column('page_number', sa.Integer, nullable=True, default=1))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('fax_extracted_fields', 'page_number')
