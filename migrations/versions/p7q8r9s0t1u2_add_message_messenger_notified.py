"""Track Messenger delivery per Allegro message.

Revision ID: p7q8r9s0t1u2
Revises: o6p7q8r9s0t1
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "p7q8r9s0t1u2"
down_revision = "o6p7q8r9s0t1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("messenger_notified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Starsze wiadomosci uznajemy za juz obsluzone; z ostatnich 24h pozwalamy
    # workerowi ponowic wysylke (np. po awarii Graph API v17).
    op.execute(
        """
        UPDATE messages
        SET messenger_notified = TRUE
        WHERE created_at < CURRENT_TIMESTAMP - INTERVAL '1 day'
        """
    )


def downgrade() -> None:
    op.drop_column("messages", "messenger_notified")
