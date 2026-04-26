"""Add unique constraint for price report items by report and offer.

Revision ID: j2k3l4m5n6o7
Revises: i1j2k3l4m5n6
Create Date: 2026-04-24 23:58:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'j2k3l4m5n6o7'
down_revision: Union[str, Sequence[str], None] = 'i1j2k3l4m5n6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PRICE_REPORTS_TABLE = 'price_reports'
PRICE_REPORT_ITEMS_TABLE = 'price_report_items'
EXCLUDED_SELLERS_TABLE = 'excluded_sellers'

CONSTRAINT_NAME = 'uq_price_report_items_report_offer'


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {column['name'] for column in inspector.get_columns(table_name)}


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {index['name'] for index in inspector.get_indexes(table_name)}


def _has_report_offer_constraint(inspector: sa.Inspector) -> bool:
    for constraint in inspector.get_unique_constraints(PRICE_REPORT_ITEMS_TABLE):
        column_names = set(constraint.get('column_names') or [])
        if constraint.get('name') == CONSTRAINT_NAME or column_names == {'report_id', 'offer_id'}:
            return True
    return False


def _create_index_if_missing(
    inspector: sa.Inspector,
    index_name: str,
    table_name: str,
    columns: list[str],
) -> None:
    if index_name not in _index_names(inspector, table_name):
        op.create_index(index_name, table_name, columns, unique=False)


def _ensure_price_reports_table(inspector: sa.Inspector) -> None:
    if not _has_table(inspector, PRICE_REPORTS_TABLE):
        op.create_table(
            PRICE_REPORTS_TABLE,
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('status', sa.String(), nullable=False, server_default='pending'),
            sa.Column('items_total', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('items_checked', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('idx_price_reports_created_at', PRICE_REPORTS_TABLE, ['created_at'], unique=False)
        op.create_index('idx_price_reports_status', PRICE_REPORTS_TABLE, ['status'], unique=False)
        return

    _create_index_if_missing(inspector, 'idx_price_reports_created_at', PRICE_REPORTS_TABLE, ['created_at'])
    _create_index_if_missing(inspector, 'idx_price_reports_status', PRICE_REPORTS_TABLE, ['status'])


def _ensure_price_report_items_table(inspector: sa.Inspector) -> bool:
    if not _has_table(inspector, PRICE_REPORT_ITEMS_TABLE):
        op.create_table(
            PRICE_REPORT_ITEMS_TABLE,
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('report_id', sa.Integer(), nullable=False),
            sa.Column('offer_id', sa.String(), nullable=False),
            sa.Column('product_name', sa.String(), nullable=True),
            sa.Column('our_price', sa.Numeric(10, 2), nullable=True),
            sa.Column('competitor_price', sa.Numeric(10, 2), nullable=True),
            sa.Column('competitor_seller', sa.String(), nullable=True),
            sa.Column('competitor_url', sa.String(), nullable=True),
            sa.Column('is_cheapest', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('price_difference', sa.Float(), nullable=True),
            sa.Column('our_position', sa.Integer(), nullable=True),
            sa.Column('total_offers', sa.Integer(), nullable=True),
            sa.Column('competitors_all_count', sa.Integer(), nullable=True),
            sa.Column('competitor_is_super_seller', sa.Boolean(), nullable=True),
            sa.Column('checked_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('error', sa.String(), nullable=True),
            sa.ForeignKeyConstraint(['report_id'], [f'{PRICE_REPORTS_TABLE}.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('report_id', 'offer_id', name=CONSTRAINT_NAME),
        )
        op.create_index('idx_price_report_items_report_id', PRICE_REPORT_ITEMS_TABLE, ['report_id'], unique=False)
        op.create_index('idx_price_report_items_offer_id', PRICE_REPORT_ITEMS_TABLE, ['offer_id'], unique=False)
        op.create_index('idx_price_report_items_is_cheapest', PRICE_REPORT_ITEMS_TABLE, ['is_cheapest'], unique=False)
        return True

    existing_columns = _column_names(inspector, PRICE_REPORT_ITEMS_TABLE)
    with op.batch_alter_table(PRICE_REPORT_ITEMS_TABLE, schema=None) as batch_op:
        if 'competitors_all_count' not in existing_columns:
            batch_op.add_column(sa.Column('competitors_all_count', sa.Integer(), nullable=True))
        if 'competitor_is_super_seller' not in existing_columns:
            batch_op.add_column(sa.Column('competitor_is_super_seller', sa.Boolean(), nullable=True))

    _create_index_if_missing(inspector, 'idx_price_report_items_report_id', PRICE_REPORT_ITEMS_TABLE, ['report_id'])
    _create_index_if_missing(inspector, 'idx_price_report_items_offer_id', PRICE_REPORT_ITEMS_TABLE, ['offer_id'])
    _create_index_if_missing(inspector, 'idx_price_report_items_is_cheapest', PRICE_REPORT_ITEMS_TABLE, ['is_cheapest'])
    return False


def _ensure_excluded_sellers_table(inspector: sa.Inspector) -> None:
    if not _has_table(inspector, EXCLUDED_SELLERS_TABLE):
        op.create_table(
            EXCLUDED_SELLERS_TABLE,
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('seller_name', sa.String(), nullable=False),
            sa.Column('excluded_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('reason', sa.String(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('seller_name'),
        )
        op.create_index('idx_excluded_sellers_name', EXCLUDED_SELLERS_TABLE, ['seller_name'], unique=False)
        return

    _create_index_if_missing(inspector, 'idx_excluded_sellers_name', EXCLUDED_SELLERS_TABLE, ['seller_name'])


def _deduplicate_rows() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    if dialect_name == 'postgresql':
        op.execute(
            sa.text(
                """
                DELETE FROM price_report_items older
                USING price_report_items newer
                WHERE older.report_id = newer.report_id
                  AND older.offer_id = newer.offer_id
                  AND older.id < newer.id
                """
            )
        )
        return

    op.execute(
        sa.text(
            """
            DELETE FROM price_report_items
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM price_report_items
                GROUP BY report_id, offer_id
            )
            """
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _ensure_price_reports_table(inspector)
    inspector = sa.inspect(bind)
    created_items_table = _ensure_price_report_items_table(inspector)
    inspector = sa.inspect(bind)
    _ensure_excluded_sellers_table(inspector)

    if created_items_table:
        return

    inspector = sa.inspect(bind)
    if _has_report_offer_constraint(inspector):
        return

    _deduplicate_rows()

    with op.batch_alter_table('price_report_items', schema=None) as batch_op:
        batch_op.create_unique_constraint(CONSTRAINT_NAME, ['report_id', 'offer_id'])


def downgrade() -> None:
    with op.batch_alter_table('price_report_items', schema=None) as batch_op:
        batch_op.drop_constraint(CONSTRAINT_NAME, type_='unique')