"""Add order contact fields and returns schema.

Revision ID: k3l4m5n6o7p8
Revises: j2k3l4m5n6o7
Create Date: 2026-04-26 17:05:00.000000

"""

from __future__ import annotations

import secrets
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'k3l4m5n6o7p8'
down_revision: Union[str, Sequence[str], None] = 'j2k3l4m5n6o7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ORDERS_TABLE = 'orders'
RETURNS_TABLE = 'returns'
RETURN_STATUS_LOGS_TABLE = 'return_status_logs'


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {column['name'] for column in inspector.get_columns(table_name)}


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {index['name'] for index in inspector.get_indexes(table_name)}


def _has_index_for_columns(
    inspector: sa.Inspector,
    table_name: str,
    columns: list[str],
) -> bool:
    expected_columns = tuple(columns)
    return any(
        tuple(index.get('column_names') or []) == expected_columns
        for index in inspector.get_indexes(table_name)
    )


def _create_index_if_missing(
    inspector: sa.Inspector,
    index_name: str,
    table_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    if index_name in _index_names(inspector, table_name):
        return
    if _has_index_for_columns(inspector, table_name, columns):
        return
    op.create_index(index_name, table_name, columns, unique=unique)


def _ensure_order_columns(inspector: sa.Inspector) -> None:
    if not _has_table(inspector, ORDERS_TABLE):
        return

    existing_columns = _column_names(inspector, ORDERS_TABLE)
    with op.batch_alter_table(ORDERS_TABLE, schema=None) as batch_op:
        if 'customer_token' not in existing_columns:
            batch_op.add_column(sa.Column('customer_token', sa.String(), nullable=True))
        if 'wfirma_invoice_id' not in existing_columns:
            batch_op.add_column(sa.Column('wfirma_invoice_id', sa.Integer(), nullable=True))
        if 'wfirma_invoice_number' not in existing_columns:
            batch_op.add_column(sa.Column('wfirma_invoice_number', sa.String(), nullable=True))
        if 'wfirma_correction_id' not in existing_columns:
            batch_op.add_column(sa.Column('wfirma_correction_id', sa.Integer(), nullable=True))
        if 'wfirma_correction_number' not in existing_columns:
            batch_op.add_column(sa.Column('wfirma_correction_number', sa.String(), nullable=True))
        if 'emails_sent' not in existing_columns:
            batch_op.add_column(sa.Column('emails_sent', sa.Text(), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(
        sa.text('SELECT order_id FROM orders WHERE customer_token IS NULL')
    ).fetchall()
    for row in rows:
        bind.execute(
            sa.text('UPDATE orders SET customer_token = :token WHERE order_id = :order_id'),
            {'token': secrets.token_urlsafe(32), 'order_id': row.order_id},
        )

    inspector = sa.inspect(bind)
    _create_index_if_missing(
        inspector,
        'idx_orders_customer_token',
        ORDERS_TABLE,
        ['customer_token'],
        unique=True,
    )


def _ensure_returns_table(inspector: sa.Inspector) -> None:
    if not _has_table(inspector, RETURNS_TABLE):
        op.create_table(
            RETURNS_TABLE,
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('order_id', sa.String(), nullable=False),
            sa.Column('status', sa.String(), nullable=False, server_default='pending'),
            sa.Column('customer_name', sa.String(), nullable=True),
            sa.Column('items_json', sa.Text(), nullable=True),
            sa.Column('return_tracking_number', sa.String(), nullable=True),
            sa.Column('return_carrier', sa.String(), nullable=True),
            sa.Column('allegro_return_id', sa.String(), nullable=True),
            sa.Column('messenger_notified', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('stock_restored', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('refund_processed', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(['order_id'], ['orders.order_id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('idx_returns_order_id', RETURNS_TABLE, ['order_id'], unique=False)
        op.create_index('idx_returns_status', RETURNS_TABLE, ['status'], unique=False)
        op.create_index('idx_returns_created_at', RETURNS_TABLE, ['created_at'], unique=False)
        return

    existing_columns = _column_names(inspector, RETURNS_TABLE)
    with op.batch_alter_table(RETURNS_TABLE, schema=None) as batch_op:
        if 'refund_processed' not in existing_columns:
            batch_op.add_column(
                sa.Column('refund_processed', sa.Boolean(), nullable=False, server_default=sa.false())
            )

    _create_index_if_missing(inspector, 'idx_returns_order_id', RETURNS_TABLE, ['order_id'])
    _create_index_if_missing(inspector, 'idx_returns_status', RETURNS_TABLE, ['status'])
    _create_index_if_missing(inspector, 'idx_returns_created_at', RETURNS_TABLE, ['created_at'])


def _ensure_return_status_logs_table(inspector: sa.Inspector) -> None:
    if not _has_table(inspector, RETURN_STATUS_LOGS_TABLE):
        op.create_table(
            RETURN_STATUS_LOGS_TABLE,
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('return_id', sa.Integer(), nullable=False),
            sa.Column('status', sa.String(), nullable=False),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('timestamp', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(['return_id'], ['returns.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(
            'idx_return_status_logs_return_id',
            RETURN_STATUS_LOGS_TABLE,
            ['return_id'],
            unique=False,
        )
        return

    _create_index_if_missing(
        inspector,
        'idx_return_status_logs_return_id',
        RETURN_STATUS_LOGS_TABLE,
        ['return_id'],
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _ensure_order_columns(inspector)
    inspector = sa.inspect(bind)
    _ensure_returns_table(inspector)
    inspector = sa.inspect(bind)
    _ensure_return_status_logs_table(inspector)


def downgrade() -> None:
    """Keep legacy data intact; this parity migration is intentionally not destructive."""