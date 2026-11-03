#!/usr/bin/env python3
"""GSC performance pulse: daily + CTR windows, freshest available."""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta

sys.path.insert(0, os.path.expanduser("~/infrastructure"))
import bw_get as bw  # noqa: E402

ITEM = "Google OAuth Retriever Shop"
SITE = "sc-domain:retrievershop.pl"


def token() -> str:
    body = urllib.parse.urlencode(
        {
            "client_id": bw.get_item(ITEM, "client_id"),
            "client_secret": bw.get_item(ITEM, "client_secret"),
            "refresh_token": bw.get_item(ITEM, "refresh_token"),
            "grant_type": "refresh_token",
        }
    ).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return json.loads(urllib.request.urlopen(req).read())["access_token"]


def query(access: str, start: str, end: str, dimensions: list[str], row_limit=50, data_state="all"):
    enc = urllib.parse.quote(SITE, safe="")
    payload = {
        "startDate": start,
        "endDate": end,
        "dimensions": dimensions,
        "rowLimit": row_limit,
        "dataState": data_state,
    }
    req = urllib.request.Request(
        f"https://www.googleapis.com/webmasters/v3/sites/{enc}/searchAnalytics/query",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.loads(r.read())
    except Exception as e:
        body = ""
        if hasattr(e, "read"):
            try:
                body = e.read().decode()[:500]
            except Exception:
                pass
        return getattr(e, "code", 0), {"error": str(e), "body": body}


def agg(rows):
    clicks = impressions = 0.0
    pos_w = 0.0
    for r in rows or []:
        c = float(r.get("clicks") or 0)
        i = float(r.get("impressions") or 0)
        p = float(r.get("position") or 0)
        clicks += c
        impressions += i
        pos_w += p * i
    return {
        "clicks": round(clicks, 1),
        "impressions": round(impressions, 1),
        "ctr": round((clicks / impressions * 100) if impressions else 0, 2),
        "position": round(pos_w / impressions, 2) if impressions else 0,
        "rows": len(rows or []),
    }


def main() -> int:
    access = token()
    today = date.today()
    out = {"today": today.isoformat(), "site": SITE}

    # Try final + all for last 16 days
    start = (today - timedelta(days=16)).isoformat()
    end = today.isoformat()
    for state in ("final", "all"):
        code, data = query(access, start, end, ["date"], 30, state)
        rows = data.get("rows") if isinstance(data, dict) else None
        daily = []
        for r in rows or []:
            daily.append(
                {
                    "date": r["keys"][0],
                    "clicks": r.get("clicks"),
                    "impressions": r.get("impressions"),
                    "ctr": round((r.get("ctr") or 0) * 100, 2),
                    "position": round(r.get("position") or 0, 2),
                }
            )
        out[f"daily_{state}"] = {"http": code, "daily": daily, "sum": agg(rows or [])}

    # Windows
    windows = {
        "last_7d": (today - timedelta(days=7), today - timedelta(days=1)),
        "prev_7d": (today - timedelta(days=14), today - timedelta(days=8)),
        "last_3d": (today - timedelta(days=3), today - timedelta(days=1)),
        "incl_today_all": (today - timedelta(days=7), today),
    }
    out["windows"] = {}
    for name, (a, b) in windows.items():
        code, data = query(access, a.isoformat(), b.isoformat(), [], 1, "all")
        rows = data.get("rows") if isinstance(data, dict) else None
        out["windows"][name] = {
            "start": a.isoformat(),
            "end": b.isoformat(),
            "http": code,
            **agg(rows or []),
            "raw_err": None if code == 200 else data,
        }

    # Top pages/queries last 7d
    a = (today - timedelta(days=7)).isoformat()
    b = (today - timedelta(days=1)).isoformat()
    for dim, key in ((["page"], "top_pages"), (["query"], "top_queries")):
        code, data = query(access, a, b, dim, 15, "all")
        rows = []
        for r in (data.get("rows") if isinstance(data, dict) else None) or []:
            rows.append(
                {
                    dim[0]: r["keys"][0],
                    "clicks": r.get("clicks"),
                    "impressions": r.get("impressions"),
                    "ctr": round((r.get("ctr") or 0) * 100, 2),
                    "position": round(r.get("position") or 0, 2),
                }
            )
        out[key] = rows

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
