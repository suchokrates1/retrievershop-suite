#!/usr/bin/env python3
"""Dump Retrievershop Uptime Kuma downs + recent pattern."""
import sqlite3
from collections import Counter
from pathlib import Path

db = Path("/app/data/kuma.db")
c = sqlite3.connect(str(db))
c.row_factory = sqlite3.Row

mons = c.execute(
    "SELECT id,name,url,interval FROM monitor WHERE lower(url) LIKE '%retriever%' OR lower(name) LIKE '%retriever%'"
).fetchall()
for m in mons:
    print("MONITOR", dict(m))
    downs = c.execute(
        """
        SELECT status, msg, time, ping
        FROM heartbeat
        WHERE monitor_id=? AND status!=1 AND time >= datetime('now','-7 day')
        ORDER BY time DESC
        """,
        (m["id"],),
    ).fetchall()
    print(f"downs_7d={len(downs)}")
    msgs = Counter()
    hours = Counter()
    for r in downs:
        msgs[r["msg"] or "?"] += 1
        # time like 2026-07-31 15:37:37.869
        t = (r["time"] or "")[:13]  # YYYY-MM-DD HH
        hours[t] += 1
        print(f"  {r['time']} status={r['status']} ping={r['ping']} msg={r['msg']}")
    print("by_msg", dict(msgs))
    print("top_hours", hours.most_common(15))

    recent = c.execute(
        """
        SELECT status, msg, time, ping
        FROM heartbeat WHERE monitor_id=?
        ORDER BY time DESC LIMIT 20
        """,
        (m["id"],),
    ).fetchall()
    print("recent:")
    for r in recent:
        print(f"  {r['time']} {r['status']} {r['ping']} {r['msg']}")
