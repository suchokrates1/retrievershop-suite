"""Link Sale to Order and switch inventory costing to weighted average (AVCO).

Wycene magazynu prowadzimy metoda sredniej wazonej kroczacej zamiast FIFO po
partiach. Ta migracja:
- sales.order_id: laczy sprzedaz z zamowieniem - realny koszt per zamowienie
  (suma Sale.purchase_cost) i odtworzenie kosztu przy zwrocie.
- sales.quantity_returned: ile sztuk z danej sprzedazy juz zwrocono
  (idempotencja zwrotow).
- product_sizes.stock_value: laczna wartosc zakupu sztuk na stanie. Srednia
  cena = stock_value / quantity. Backfill = quantity * srednia wazona z historii
  partii (PurchaseBatch).
- usuwa purchase_batches.remaining_quantity (dodana wczesniej dla FIFO,
  nieuzywana przy sredniej). PurchaseBatch zostaje jako dziennik dostaw.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision: str = "n1o2p3q4r5s6"
down_revision: Union[str, Sequence[str], None] = "m5n6o7p8q9r0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- sales: powiazanie z zamowieniem + licznik zwrotow ---
    with op.batch_alter_table("sales", schema=None) as batch_op:
        batch_op.add_column(sa.Column("order_id", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "quantity_returned",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.create_foreign_key(
            "fk_sales_order_id_orders",
            "orders",
            ["order_id"],
            ["order_id"],
            ondelete="SET NULL",
        )
    op.create_index("idx_sales_order_id", "sales", ["order_id"], unique=False)

    # --- product_sizes: wartosc magazynu dla sredniej wazonej ---
    with op.batch_alter_table("product_sizes", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "stock_value",
                sa.Numeric(12, 2),
                nullable=False,
                server_default="0",
            )
        )

    # Backfill stock_value = quantity * srednia wazona cena z historii partii.
    # Liczone w Pythonie (Decimal), zeby byc niezaleznym od dialektu - na
    # PostgreSQL ROUND(double precision, int) nie istnieje, a dzielenie
    # calkowitoliczbowe na SQLite dawaloby zle wyniki.
    bind = op.get_bind()
    avg_rows = bind.execute(
        text(
            "SELECT product_id, size, "
            "SUM(quantity * price) AS total_value, "
            "SUM(quantity) AS total_qty "
            "FROM purchase_batches WHERE quantity > 0 "
            "GROUP BY product_id, size"
        )
    ).fetchall()
    avg_by_key = {}
    for row in avg_rows:
        total_qty = row.total_qty or 0
        if total_qty > 0:
            avg_by_key[(row.product_id, row.size)] = Decimal(str(row.total_value)) / Decimal(str(total_qty))

    for ps in bind.execute(
        text("SELECT id, product_id, size, quantity FROM product_sizes")
    ).fetchall():
        avg = avg_by_key.get((ps.product_id, ps.size))
        qty = ps.quantity or 0
        if avg is None or qty <= 0:
            continue
        value = (avg * Decimal(qty)).quantize(Decimal("0.01"))
        bind.execute(
            text("UPDATE product_sizes SET stock_value = :value WHERE id = :id"),
            {"value": str(value), "id": ps.id},
        )

    # --- usuniecie sladu FIFO (kolumne dodala migracja a1b2c3d4e5f6) ---
    with op.batch_alter_table("purchase_batches", schema=None) as batch_op:
        batch_op.drop_column("remaining_quantity")


def downgrade() -> None:
    with op.batch_alter_table("purchase_batches", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("remaining_quantity", sa.Integer(), nullable=True)
        )
    op.execute(
        "UPDATE purchase_batches SET remaining_quantity = quantity "
        "WHERE remaining_quantity IS NULL"
    )

    with op.batch_alter_table("product_sizes", schema=None) as batch_op:
        batch_op.drop_column("stock_value")

    op.drop_index("idx_sales_order_id", table_name="sales")
    with op.batch_alter_table("sales", schema=None) as batch_op:
        batch_op.drop_constraint("fk_sales_order_id_orders", type_="foreignkey")
        batch_op.drop_column("quantity_returned")
        batch_op.drop_column("order_id")
