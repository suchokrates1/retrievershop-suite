"""Add return shipping instruction fields.

Revision ID: t1u2v3w4x5y6
Revises: s0t1u2v3w4x5
Create Date: 2026-07-23 13:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "t1u2v3w4x5y6"
down_revision = "s0t1u2v3w4x5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "returns",
        sa.Column("return_ship_method", sa.String(), nullable=True),
    )
    op.add_column(
        "returns",
        sa.Column("return_instruction_token", sa.String(), nullable=True),
    )
    op.add_column(
        "returns",
        sa.Column("return_code", sa.String(), nullable=True),
    )
    op.add_column(
        "returns",
        sa.Column("return_code_expires_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "returns",
        sa.Column("return_ship_deadline", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_returns_return_instruction_token",
        "returns",
        ["return_instruction_token"],
        unique=True,
    )


def downgrade():
    op.drop_index("ix_returns_return_instruction_token", table_name="returns")
    op.drop_column("returns", "return_ship_deadline")
    op.drop_column("returns", "return_code_expires_at")
    op.drop_column("returns", "return_code")
    op.drop_column("returns", "return_instruction_token")
    op.drop_column("returns", "return_ship_method")
