"""Cache tresci Allegro + mapowanie Woo product.

Revision ID: q8r9s0t1u2v3
Revises: p7q8r9s0t1u2
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "q8r9s0t1u2v3"
down_revision = "p7q8r9s0t1u2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("allegro_offers", sa.Column("description_html", sa.Text(), nullable=True))
    op.add_column("allegro_offers", sa.Column("image_urls", sa.Text(), nullable=True))
    op.add_column("allegro_offers", sa.Column("content_synced_at", sa.String(), nullable=True))
    op.add_column("product_sizes", sa.Column("woo_variation_id", sa.Integer(), nullable=True))
    op.add_column("products", sa.Column("woo_product_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "woo_product_id")
    op.drop_column("product_sizes", "woo_variation_id")
    op.drop_column("allegro_offers", "content_synced_at")
    op.drop_column("allegro_offers", "image_urls")
    op.drop_column("allegro_offers", "description_html")
