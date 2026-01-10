"""Add ean column to allegro_offers

Revision ID: c48d170e3749
Revises: b2c3d4e5f6a7
Create Date: 2026-01-10 22:10:32.692179

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c48d170e3749'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('allegro_offers', sa.Column('ean', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('allegro_offers', 'ean')
