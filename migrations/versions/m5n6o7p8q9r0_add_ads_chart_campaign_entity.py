"""Add campaign_entity_id to allegro_ads_chart_daily for per-campaign charts."""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "m5n6o7p8q9r0"
down_revision: Union[str, Sequence[str], None] = "l4m5n6o7p8q9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "allegro_ads_chart_daily",
        sa.Column("campaign_entity_id", sa.String(), nullable=False, server_default=""),
    )
    op.drop_constraint("uq_ads_chart_snapshot_day", "allegro_ads_chart_daily", type_="unique")
    op.create_unique_constraint(
        "uq_ads_chart_snapshot_campaign_day",
        "allegro_ads_chart_daily",
        ["snapshot_id", "campaign_entity_id", "day"],
    )
    op.create_index(
        "idx_allegro_ads_chart_daily_campaign",
        "allegro_ads_chart_daily",
        ["campaign_entity_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_allegro_ads_chart_daily_campaign", table_name="allegro_ads_chart_daily")
    op.drop_constraint("uq_ads_chart_snapshot_campaign_day", "allegro_ads_chart_daily", type_="unique")
    op.create_unique_constraint(
        "uq_ads_chart_snapshot_day",
        "allegro_ads_chart_daily",
        ["snapshot_id", "day"],
    )
    op.drop_column("allegro_ads_chart_daily", "campaign_entity_id")
