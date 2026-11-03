"""Oferta katalogowa, jedna na produkt.

Revision ID: v3w4x5y6z7a8
Revises: u2v3w4x5y6z7
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "v3w4x5y6z7a8"
down_revision = "u2v3w4x5y6z7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "product_offers" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "product_offers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(), nullable=False, server_default=""),
        sa.Column("description_html", sa.Text(), nullable=True),
        sa.Column("image_urls", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="manual"),
        sa.Column("allegro_offer_id", sa.String(), nullable=True),
        sa.Column("updated_at", sa.String(), nullable=True),
        sa.UniqueConstraint("product_id", name="uq_product_offers_product_id"),
    )


def downgrade() -> None:
    op.drop_table("product_offers")
