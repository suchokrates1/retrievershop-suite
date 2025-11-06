import importlib
import pytest

import magazyn.config as cfg


def _prepare_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(cfg.settings, "DB_PATH", str(db_path))

    pkg = importlib.import_module("magazyn")
    importlib.reload(pkg)

    db_mod = importlib.import_module("magazyn.db")
    db = importlib.reload(db_mod)
    db.configure_engine(cfg.settings.DB_PATH)
    return db, db_path


@pytest.mark.skip(reason="Legacy migration system replaced by Alembic")
def test_migration_repoints_price_history_fk(tmp_path, monkeypatch):
    db, db_path = _prepare_db(tmp_path, monkeypatch)

    with db.sqlite_connect(db_path, apply_pragmas=False) as conn:
        conn.executescript(
            """
            PRAGMA foreign_keys=OFF;
            CREATE TABLE products (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                color TEXT
            );
            CREATE TABLE product_sizes (
                id INTEGER PRIMARY KEY,
                product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                size TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0,
                barcode TEXT UNIQUE
            );
            CREATE TABLE allegro_offers (
                id INTEGER PRIMARY KEY,
                offer_id TEXT UNIQUE,
                title TEXT NOT NULL,
                price NUMERIC(10,2) NOT NULL,
                product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
                product_size_id INTEGER REFERENCES product_sizes(id) ON DELETE SET NULL,
                synced_at TEXT
            );
            CREATE TABLE allegro_price_history (
                id INTEGER PRIMARY KEY,
                offer_id TEXT,
                product_size_id INTEGER REFERENCES allegro_offers(id) ON DELETE SET NULL,
                price NUMERIC(10,2) NOT NULL,
                recorded_at TEXT NOT NULL
            );
            INSERT INTO products (id, name, color) VALUES (1, 'Widget', 'blue');
            INSERT INTO product_sizes (id, product_id, size, quantity)
            VALUES (1, 1, 'M', 5);
            INSERT INTO allegro_offers (
                id, offer_id, title, price, product_id, product_size_id, synced_at
            )
            VALUES (1, 'offer-1', 'Widget offer', 10.0, 1, 1, NULL);
            INSERT INTO allegro_price_history (id, offer_id, product_size_id, price, recorded_at)
            VALUES (1, 'offer-1', 1, 10.0, '2024-01-01T00:00:00Z');
            """
        )
        conn.commit()

    db.init_db()
    db.apply_migrations()

    with db.sqlite_connect(db_path) as conn:
        fk_rows = conn.execute(
            "PRAGMA foreign_key_list('allegro_price_history')"
        ).fetchall()

    assert any(row[2] == "product_sizes" and (row[6] or "").upper() == "SET NULL" for row in fk_rows)

    allegro_prices = importlib.import_module("magazyn.domain.allegro_prices")
    allegro_prices = importlib.reload(allegro_prices)

    with db.sqlite_connect(db_path) as conn:
        before_count = conn.execute(
            "SELECT COUNT(*) FROM allegro_price_history"
        ).fetchone()[0]

    session = db.SessionLocal()
    try:
        allegro_prices.record_price_point(
            session,
            offer_id="offer-2",
            product_size_id=1,
            price="12.34",
            recorded_at="2024-02-01T00:00:00Z",
        )
        session.commit()
    finally:
        session.close()

    with db.sqlite_connect(db_path) as conn:
        after_count = conn.execute(
            "SELECT COUNT(*) FROM allegro_price_history"
        ).fetchone()[0]

    assert after_count == before_count + 1
