"""Add Allegro Ads Panel snapshot tables."""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "l4m5n6o7p8q9"
down_revision: Union[str, Sequence[str], None] = "k3l4m5n6o7p8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "allegro_ads_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("marketplace_id", sa.String(), nullable=False, server_default="allegro-pl"),
        sa.Column("scope_id_b64", sa.String(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="ok"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_allegro_ads_snapshots_snapshot_date", "allegro_ads_snapshots", ["snapshot_date"])
    op.create_index("idx_allegro_ads_snapshots_status", "allegro_ads_snapshots", ["status"])

    op.create_table(
        "allegro_ads_campaign_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("allegro_ads_snapshots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_entity_id", sa.String(), nullable=False),
        sa.Column("campaign_name", sa.String(), nullable=False),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ctr", sa.Numeric(8, 4), nullable=True),
        sa.Column("cpc", sa.Numeric(10, 2), nullable=True),
        sa.Column("cost", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("roi", sa.Numeric(10, 2), nullable=True),
        sa.Column("interest", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sale_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sale_value", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.UniqueConstraint("snapshot_id", "campaign_entity_id", name="uq_ads_campaign_snapshot_entity"),
    )
    op.create_index("idx_allegro_ads_campaign_daily_entity", "allegro_ads_campaign_daily", ["campaign_entity_id"])

    op.create_table(
        "allegro_ads_sold_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "campaign_daily_id",
            sa.Integer(),
            sa.ForeignKey("allegro_ads_campaign_daily.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("offer_id", sa.String(), nullable=False),
        sa.Column("offer_name", sa.String(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sale_value", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.UniqueConstraint("campaign_daily_id", "offer_id", name="uq_ads_sold_item_campaign_offer"),
    )
    op.create_index("idx_allegro_ads_sold_items_offer_id", "allegro_ads_sold_items", ["offer_id"])

    op.create_table(
        "allegro_ads_chart_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("allegro_ads_snapshots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("sale_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sale_value", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("ctr", sa.Numeric(8, 4), nullable=True),
        sa.Column("cpc", sa.Numeric(10, 2), nullable=True),
        sa.Column("roi", sa.Numeric(10, 2), nullable=True),
        sa.UniqueConstraint("snapshot_id", "day", name="uq_ads_chart_snapshot_day"),
    )
    op.create_index("idx_allegro_ads_chart_daily_day", "allegro_ads_chart_daily", ["day"])


def downgrade() -> None:
    op.drop_index("idx_allegro_ads_chart_daily_day", table_name="allegro_ads_chart_daily")
    op.drop_table("allegro_ads_chart_daily")
    op.drop_index("idx_allegro_ads_sold_items_offer_id", table_name="allegro_ads_sold_items")
    op.drop_table("allegro_ads_sold_items")
    op.drop_index("idx_allegro_ads_campaign_daily_entity", table_name="allegro_ads_campaign_daily")
    op.drop_table("allegro_ads_campaign_daily")
    op.drop_index("idx_allegro_ads_snapshots_status", table_name="allegro_ads_snapshots")
    op.drop_index("idx_allegro_ads_snapshots_snapshot_date", table_name="allegro_ads_snapshots")
    op.drop_table("allegro_ads_snapshots")
