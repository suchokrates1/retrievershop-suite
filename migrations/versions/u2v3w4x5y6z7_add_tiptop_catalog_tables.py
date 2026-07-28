"""Add TipTop24 catalog, links and reorder exclusion tables.

Revision ID: u2v3w4x5y6z7
Revises: t1u2v3w4x5y6
Create Date: 2026-07-28 12:15:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "u2v3w4x5y6z7"
down_revision: Union[str, Sequence[str], None] = "t1u2v3w4x5y6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tiptop_products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tiptop_product_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("producer", sa.String(), nullable=True),
        sa.Column(
            "scraped_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("tiptop_product_id", name="uq_tiptop_products_product_id"),
    )
    op.create_index(
        "idx_tiptop_products_product_id",
        "tiptop_products",
        ["tiptop_product_id"],
        unique=True,
    )

    op.create_table(
        "tiptop_variants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tiptop_product_id", sa.Integer(), nullable=False),
        sa.Column("option_map", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("size_label", sa.String(), nullable=True),
        sa.Column("color_label", sa.String(), nullable=True),
        sa.Column("variant_stock_id", sa.Integer(), nullable=True),
        sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("price", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tiptop_product_id"],
            ["tiptop_products.tiptop_product_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tiptop_product_id",
            "size_label",
            "color_label",
            name="uq_tiptop_variants_product_size_color",
        ),
    )
    op.create_index(
        "idx_tiptop_variants_product_id",
        "tiptop_variants",
        ["tiptop_product_id"],
    )

    op.create_table(
        "tiptop_product_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_size_id", sa.Integer(), nullable=False),
        sa.Column("tiptop_variant_id", sa.Integer(), nullable=False),
        sa.Column("match_confidence", sa.Float(), nullable=True),
        sa.Column("match_type", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["product_size_id"],
            ["product_sizes.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tiptop_variant_id"],
            ["tiptop_variants.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("product_size_id", name="uq_tiptop_links_product_size"),
    )
    op.create_index(
        "idx_tiptop_links_variant_id",
        "tiptop_product_links",
        ["tiptop_variant_id"],
    )

    op.create_table(
        "tiptop_reorder_exclusions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("product_size_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_size_id"],
            ["product_sizes.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "idx_tiptop_excl_product_id",
        "tiptop_reorder_exclusions",
        ["product_id"],
    )
    op.create_index(
        "idx_tiptop_excl_product_size_id",
        "tiptop_reorder_exclusions",
        ["product_size_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_tiptop_excl_product_size_id", table_name="tiptop_reorder_exclusions")
    op.drop_index("idx_tiptop_excl_product_id", table_name="tiptop_reorder_exclusions")
    op.drop_table("tiptop_reorder_exclusions")
    op.drop_index("idx_tiptop_links_variant_id", table_name="tiptop_product_links")
    op.drop_table("tiptop_product_links")
    op.drop_index("idx_tiptop_variants_product_id", table_name="tiptop_variants")
    op.drop_table("tiptop_variants")
    op.drop_index("idx_tiptop_products_product_id", table_name="tiptop_products")
    op.drop_table("tiptop_products")
