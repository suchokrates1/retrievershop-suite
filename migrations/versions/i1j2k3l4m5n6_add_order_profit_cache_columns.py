"""Add cached real profit columns to orders.

Revision ID: i1j2k3l4m5n6
Revises: h9c0d1e2f3g4
Create Date: 2026-04-23 20:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'i1j2k3l4m5n6'
down_revision = 'h9c0d1e2f3g4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('orders', sa.Column('real_profit_sale_price', sa.Numeric(10, 2), nullable=True))
    op.add_column('orders', sa.Column('real_profit_purchase_cost', sa.Numeric(10, 2), nullable=True))
    op.add_column('orders', sa.Column('real_profit_packaging_cost', sa.Numeric(10, 2), nullable=True))
    op.add_column('orders', sa.Column('real_profit_allegro_fees', sa.Numeric(10, 2), nullable=True))
    op.add_column('orders', sa.Column('real_profit_amount', sa.Numeric(10, 2), nullable=True))
    op.add_column('orders', sa.Column('real_profit_fee_source', sa.String(length=32), nullable=True))
    op.add_column('orders', sa.Column('real_profit_shipping_estimated', sa.Boolean(), nullable=True))
    op.add_column('orders', sa.Column('real_profit_is_final', sa.Boolean(), nullable=True))
    op.add_column('orders', sa.Column('real_profit_error', sa.Text(), nullable=True))
    op.add_column('orders', sa.Column('real_profit_updated_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('orders', 'real_profit_updated_at')
    op.drop_column('orders', 'real_profit_error')
    op.drop_column('orders', 'real_profit_is_final')
    op.drop_column('orders', 'real_profit_shipping_estimated')
    op.drop_column('orders', 'real_profit_fee_source')
    op.drop_column('orders', 'real_profit_amount')
    op.drop_column('orders', 'real_profit_allegro_fees')
    op.drop_column('orders', 'real_profit_packaging_cost')
    op.drop_column('orders', 'real_profit_purchase_cost')
    op.drop_column('orders', 'real_profit_sale_price')