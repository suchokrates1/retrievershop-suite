"""Add read column to threads

Revision ID: 65a19d858818
Revises:
Create Date: 2025-11-04 19:26:58.598501

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


# revision identifiers, used by Alembic.
revision: str = '65a19d858818'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "threads"):
        op.create_table(
            "threads",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("author", sa.String(), nullable=False),
            sa.Column(
                "last_message_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("type", sa.String(), nullable=False),
            sa.Column("read", sa.Boolean(), server_default=sa.text("0"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    elif not _has_column(inspector, "threads", "read"):
        op.add_column(
            "threads",
            sa.Column("read", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        )
        op.execute(sa.text("UPDATE threads SET read = 0 WHERE read IS NULL"))

    if not _has_table(inspector, "messages"):
        op.create_table(
            "messages",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("thread_id", sa.String(), nullable=False),
            sa.Column("author", sa.String(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('messages')
    op.drop_table('threads')
