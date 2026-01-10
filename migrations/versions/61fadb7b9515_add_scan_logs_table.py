"""Add scan_logs table for barcode/label scan history

Revision ID: 61fadb7b9515
Revises: a1b2c3d4e5f6
Create Date: 2026-01-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '61fadb7b9515'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'scan_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('scan_type', sa.String(), nullable=False),
        sa.Column('barcode', sa.String(), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('result_data', sa.Text(), nullable=True),
        sa.Column('error_message', sa.String(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_scan_logs_created_at', 'scan_logs', ['created_at'], unique=False)
    op.create_index('idx_scan_logs_scan_type', 'scan_logs', ['scan_type'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_scan_logs_scan_type', table_name='scan_logs')
    op.drop_index('idx_scan_logs_created_at', table_name='scan_logs')
    op.drop_table('scan_logs')
