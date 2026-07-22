"""Add woo_withdrawal_id to returns.

Revision ID: s0t1u2v3w4x5
Revises: r9s0t1u2v3w4
Create Date: 2026-07-22 20:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "s0t1u2v3w4x5"
down_revision = "r9s0t1u2v3w4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "returns",
        sa.Column("woo_withdrawal_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_returns_woo_withdrawal_id",
        "returns",
        ["woo_withdrawal_id"],
        unique=True,
    )


def downgrade():
    op.drop_index("ix_returns_woo_withdrawal_id", table_name="returns")
    op.drop_column("returns", "woo_withdrawal_id")
