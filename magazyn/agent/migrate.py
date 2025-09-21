"""CLI utilities for migrating legacy label agent data."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Iterable, Optional

from magazyn.db import sqlite_connect
from magazyn.print_agent import AgentConfig, LabelAgent, load_config

LOGGER = logging.getLogger(__name__)


def migrate_printed_file(db_path: str, printed_file: Path) -> None:
    if not printed_file.exists():
        LOGGER.info("Printed orders file %s not found, skipping", printed_file)
        return
    conn = sqlite_connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM printed_orders")
    if cur.fetchone()[0]:
        LOGGER.info("printed_orders table already populated, skipping text file import")
        conn.close()
        return
    with printed_file.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or "," not in line:
                continue
            order_id, ts = line.split(",", 1)
            cur.execute(
                "INSERT OR IGNORE INTO printed_orders(order_id, printed_at) VALUES (?, ?)",
                (order_id.strip(), ts.strip()),
            )
    conn.commit()
    conn.close()
    LOGGER.info("Imported printed orders from %s", printed_file)


def migrate_queue_file(db_path: str, queue_file: Path) -> None:
    if not queue_file.exists():
        LOGGER.info("Queued labels file %s not found, skipping", queue_file)
        return
    conn = sqlite_connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM label_queue")
    if cur.fetchone()[0]:
        LOGGER.info("label_queue table already populated, skipping jsonl import")
        conn.close()
        return
    with queue_file.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                LOGGER.error("Invalid JSON entry in %s: %s", queue_file, line)
                continue
            cur.execute(
                "INSERT INTO label_queue(order_id, label_data, ext, last_order_data) VALUES (?, ?, ?, ?)",
                (
                    item.get("order_id"),
                    item.get("label_data"),
                    item.get("ext"),
                    json.dumps(item.get("last_order_data", {})),
                ),
            )
    conn.commit()
    conn.close()
    LOGGER.info("Imported queued labels from %s", queue_file)


def migrate_from_legacy_db(db_path: str, legacy_db: Path) -> None:
    if not legacy_db.exists():
        LOGGER.info("Legacy database %s not found, skipping", legacy_db)
        return
    conn = sqlite_connect(db_path)
    cur = conn.cursor()
    old_conn = sqlite_connect(legacy_db)
    old_cur = old_conn.cursor()
    try:
        for table, columns in (("printed_orders", 3), ("label_queue", 4)):
            old_cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            )
            if not old_cur.fetchone():
                continue
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            if cur.fetchone()[0]:
                continue
            placeholders = ",".join(["?"] * columns)
            for row in old_cur.execute(f"SELECT * FROM {table}"):
                cur.execute(f"INSERT INTO {table} VALUES ({placeholders})", row)
        conn.commit()
    finally:
        old_conn.close()
        conn.close()
    LOGGER.info("Imported data from legacy database %s", legacy_db)


def run_migrations(agent: LabelAgent, *, printed_file: Optional[Path], queue_file: Optional[Path], legacy_db: Optional[Path]) -> None:
    agent.ensure_db()
    if printed_file:
        migrate_printed_file(agent.config.db_file, printed_file)
    if queue_file:
        migrate_queue_file(agent.config.db_file, queue_file)
    if legacy_db:
        migrate_from_legacy_db(agent.config.db_file, legacy_db)


def build_agent(args: argparse.Namespace) -> LabelAgent:
    settings_obj = load_config()
    config = AgentConfig.from_settings(settings_obj)
    updates = {}
    if args.db_file:
        updates["db_file"] = str(args.db_file)
    if args.printed_file:
        updates["legacy_printed_file"] = str(args.printed_file)
    if args.queue_file:
        updates["legacy_queue_file"] = str(args.queue_file)
    if args.legacy_db:
        updates["legacy_db_file"] = str(args.legacy_db)
    if updates:
        config = config.with_updates(**updates)
    agent = LabelAgent(config, settings_obj)
    return agent


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate legacy label agent data")
    parser.add_argument("--db-file", type=Path, help="Path to the SQLite database")
    parser.add_argument(
        "--printed-file",
        type=Path,
        help="Path to the legacy printed orders text file",
    )
    parser.add_argument(
        "--queue-file",
        type=Path,
        help="Path to the legacy queued labels JSONL file",
    )
    parser.add_argument(
        "--legacy-db",
        type=Path,
        help="Path to the legacy standalone SQLite database",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    agent = build_agent(args)
    printed_default = agent.config.legacy_printed_file
    queue_default = agent.config.legacy_queue_file
    legacy_db_default = agent.config.legacy_db_file

    printed_file = Path(args.printed_file) if args.printed_file else (Path(printed_default) if printed_default else None)
    queue_file = Path(args.queue_file) if args.queue_file else (Path(queue_default) if queue_default else None)
    legacy_db = Path(args.legacy_db) if args.legacy_db else (Path(legacy_db_default) if legacy_db_default else None)

    run_migrations(
        agent,
        printed_file=printed_file if printed_file and printed_file.exists() else None,
        queue_file=queue_file if queue_file and queue_file.exists() else None,
        legacy_db=legacy_db if legacy_db and legacy_db.exists() else None,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
