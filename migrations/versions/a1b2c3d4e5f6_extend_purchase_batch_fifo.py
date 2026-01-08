"""Extend PurchaseBatch for FIFO tracking

Revision ID: a1b2c3d4e5f6
Revises: 9107f16139f0
Create Date: 2026-01-08

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '9107f16139f0'
branch_labels = None
depends_on = None


def upgrade():
    # Add new columns to purchase_batches table
    with op.batch_alter_table('purchase_batches', schema=None) as batch_op:
        batch_op.add_column(sa.Column('remaining_quantity', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('barcode', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('invoice_number', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('supplier', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('notes', sa.Text(), nullable=True))
    
    # Set remaining_quantity = quantity for existing records (they haven't been consumed yet)
    op.execute("UPDATE purchase_batches SET remaining_quantity = quantity WHERE remaining_quantity IS NULL")
    
    # Create indexes
    op.create_index('idx_purchase_batches_product_size', 'purchase_batches', ['product_id', 'size'], unique=False)
    op.create_index('idx_purchase_batches_barcode', 'purchase_batches', ['barcode'], unique=False)
    op.create_index('idx_purchase_batches_date', 'purchase_batches', ['purchase_date'], unique=False)


def downgrade():
    # Drop indexes
    op.drop_index('idx_purchase_batches_date', table_name='purchase_batches')
    op.drop_index('idx_purchase_batches_barcode', table_name='purchase_batches')
    op.drop_index('idx_purchase_batches_product_size', table_name='purchase_batches')
    
    # Drop columns
    with op.batch_alter_table('purchase_batches', schema=None) as batch_op:
        batch_op.drop_column('notes')
        batch_op.drop_column('supplier')
        batch_op.drop_column('invoice_number')
        batch_op.drop_column('barcode')
        batch_op.drop_column('remaining_quantity')
