"""Add unique constraint for price report items by report and offer.

Revision ID: j2k3l4m5n6o7
Revises: i1j2k3l4m5n6
Create Date: 2026-04-24 23:58:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'j2k3l4m5n6o7'
down_revision: Union[str, Sequence[str], None] = 'i1j2k3l4m5n6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CONSTRAINT_NAME = 'uq_price_report_items_report_offer'


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
    _deduplicate_rows()

    with op.batch_alter_table('price_report_items', schema=None) as batch_op:
        batch_op.create_unique_constraint(CONSTRAINT_NAME, ['report_id', 'offer_id'])


def downgrade() -> None:
    with op.batch_alter_table('price_report_items', schema=None) as batch_op:
        batch_op.drop_constraint(CONSTRAINT_NAME, type_='unique')