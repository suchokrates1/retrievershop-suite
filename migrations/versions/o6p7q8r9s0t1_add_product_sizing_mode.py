"""Add explicit product sizing mode.

Revision ID: o6p7q8r9s0t1
Revises: n1o2p3q4r5s6
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "o6p7q8r9s0t1"
down_revision = "n1o2p3q4r5s6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("sizing_mode", sa.String(length=16), nullable=True))
    # Only unambiguous legacy products are backfilled. Mixed products remain
    # NULL deliberately: their inventory needs the audited repair path rather
    # than an arbitrary choice of size family.
    op.execute(
        """
        UPDATE products
        SET sizing_mode = CASE
            WHEN EXISTS (
                SELECT 1 FROM product_sizes ps
                WHERE ps.product_id = products.id
                  AND ps.size = 'Uniwersalny'
                  AND (ps.quantity <> 0 OR ps.barcode IS NOT NULL)
            )
            AND NOT EXISTS (
                SELECT 1 FROM product_sizes ps
                WHERE ps.product_id = products.id
                  AND ps.size <> 'Uniwersalny'
                  AND (ps.quantity <> 0 OR ps.barcode IS NOT NULL)
            )
            THEN 'universal'
            WHEN NOT EXISTS (
                SELECT 1 FROM product_sizes ps
                WHERE ps.product_id = products.id
                  AND ps.size = 'Uniwersalny'
                  AND (ps.quantity <> 0 OR ps.barcode IS NOT NULL)
            )
            THEN 'sized'
            ELSE NULL
        END
        """
    )


def downgrade() -> None:
    op.drop_column("products", "sizing_mode")
