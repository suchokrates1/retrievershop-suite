"""Create stocktakes and stocktake_items tables

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-02-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, None] = 'd5e6f7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'stocktakes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='in_progress'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_stocktakes_status', 'stocktakes', ['status'])

    op.create_table(
        'stocktake_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('stocktake_id', sa.Integer(), nullable=False),
        sa.Column('product_size_id', sa.Integer(), nullable=False),
        sa.Column('expected_qty', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('scanned_qty', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('scanned_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['stocktake_id'], ['stocktakes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['product_size_id'], ['product_sizes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_stocktake_items_stocktake_id', 'stocktake_items', ['stocktake_id'])
    op.create_index('idx_stocktake_items_product_size_id', 'stocktake_items', ['stocktake_id', 'product_size_id'])


def downgrade() -> None:
    op.drop_table('stocktake_items')
    op.drop_table('stocktakes')
