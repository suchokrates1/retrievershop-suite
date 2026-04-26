"""Wspolne helpery filtrow, formatowania i eksportu dla API statystyk."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import io

import pandas as pd
from flask import Response, jsonify, request


@dataclass
class StatsFilters:
    date_from: datetime
    date_to: datetime
    granularity: str
    platform: str
    payment_type: str


def json_error(code: str, message: str, status: int = 400):
    return (
        jsonify(
            {
                "ok": False,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "data": None,
                "errors": [{"code": code, "message": message}],
            }
        ),
        status,
    )


def parse_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None


def parse_filters() -> tuple[StatsFilters | None, tuple | None]:
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    default_from = today.replace(day=1)
    default_to = today + timedelta(days=1)

    date_from_raw = (request.args.get("date_from") or "").strip()
    date_to_raw = (request.args.get("date_to") or "").strip()
    granularity = (request.args.get("granularity") or "day").strip().lower()
    platform = (request.args.get("platform") or "all").strip().lower()
    payment_type = (request.args.get("payment_type") or "all").strip().lower()

    if granularity not in {"day", "week", "month"}:
        return None, json_error(
            "INVALID_GRANULARITY", "Dozwolone granularity: day, week, month"
        )

    if platform not in {"all", "allegro", "shop", "ebay", "manual"}:
        return None, json_error(
            "INVALID_PLATFORM", "Dozwolone platform: all, allegro, shop, ebay, manual"
        )

    if payment_type not in {"all", "cod", "online"}:
        return None, json_error(
            "INVALID_PAYMENT_TYPE", "Dozwolone payment_type: all, cod, online"
        )

    if date_from_raw:
        date_from = parse_date(date_from_raw)
        if not date_from:
            return None, json_error(
                "INVALID_DATE_FROM", "date_from musi miec format YYYY-MM-DD"
            )
    else:
        date_from = default_from

    if date_to_raw:
        date_to = parse_date(date_to_raw)
        if not date_to:
            return None, json_error(
                "INVALID_DATE_TO", "date_to musi miec format YYYY-MM-DD"
            )
        date_to = date_to + timedelta(days=1)
    else:
        date_to = default_to

    if date_from >= date_to:
        return None, json_error(
            "INVALID_DATE_RANGE", "date_from musi byc mniejsze niz date_to"
        )

    return StatsFilters(
        date_from=date_from,
        date_to=date_to,
        granularity=granularity,
        platform=platform,
        payment_type=payment_type,
    ), None


def build_cache_key(filters: StatsFilters) -> str:
    return "|".join(
        [
            filters.date_from.strftime("%Y-%m-%d"),
            filters.date_to.strftime("%Y-%m-%d"),
            filters.granularity,
            filters.platform,
            filters.payment_type,
        ]
    )


def to_ts(dt: datetime) -> int:
    return int(dt.timestamp())


def pct_change(current: Decimal, previous: Decimal) -> float | None:
    if previous == 0:
        return None
    return float(((current - previous) / previous) * 100)


def period_offsets(filters: StatsFilters) -> tuple[int, int, int, int]:
    current_start = to_ts(filters.date_from)
    current_end = to_ts(filters.date_to)
    period_len = filters.date_to - filters.date_from
    prev_start = to_ts(filters.date_from - period_len)
    prev_end = current_start
    return current_start, current_end, prev_start, prev_end


def format_filters(filters: StatsFilters) -> dict[str, str]:
    return {
        "date_from": filters.date_from.strftime("%Y-%m-%d"),
        "date_to": (filters.date_to - timedelta(days=1)).strftime("%Y-%m-%d"),
        "granularity": filters.granularity,
        "platform": filters.platform,
        "payment_type": filters.payment_type,
    }


def export_table(rows: list[dict], filename_prefix: str, export_format: str) -> Response:
    if export_format == "csv":
        output = io.StringIO()
        fieldnames = list(rows[0].keys()) if rows else ["empty"]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        content = output.getvalue()
        return Response(
            content,
            mimetype="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename_prefix}.csv",
            },
        )

    if export_format == "xlsx":
        df = pd.DataFrame(rows or [{"empty": "no-data"}])
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="stats")
        buffer.seek(0)
        return Response(
            buffer.read(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename={filename_prefix}.xlsx",
            },
        )

    return json_error("INVALID_EXPORT_FORMAT", "Dozwolone formaty eksportu: csv, xlsx")


__all__ = [
    "StatsFilters",
    "build_cache_key",
    "export_table",
    "format_filters",
    "json_error",
    "parse_date",
    "parse_filters",
    "pct_change",
    "period_offsets",
    "to_ts",
]