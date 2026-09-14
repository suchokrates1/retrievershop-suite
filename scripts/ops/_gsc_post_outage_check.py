#!/usr/bin/env python3
"""Post-outage GSC + Merchant pulse for retrievershop.pl."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, timedelta

sys.path.insert(0, os.path.expanduser("~/infrastructure"))
import bw_get as bw  # noqa: E402

from _merchant_api import issue_servability, list_products, merchant_id

ITEM = "Google OAuth Retriever Shop"
SITE = "sc-domain:retrievershop.pl"
URLS = [
    "https://retrievershop.pl/",
    "https://retrievershop.pl/blog/",
    "https://retrievershop.pl/produkt/szelki-dla-psa-truelove-front-line-premium/",
    "https://retrievershop.pl/produkt/szelki-dla-psa-truelove-front-line/",
    "https://retrievershop.pl/kapok-dla-psa-truelove-dive-kiedy-warto/",
    "https://retrievershop.pl/bezpieczenstwo-psa-po-zmroku-szelki-lumen-led/",
]


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


def api(url: str, access: str, method: str = "GET", data: bytes | None = None):
    headers = {"Authorization": f"Bearer {access}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:2000]


def inspect(access: str, page: str, live: bool = False):
    body = {"inspectionUrl": page, "siteUrl": SITE}
    if live:
        # live is separate endpoint nuance — standard inspect is enough; use inspectionResult
        pass
    enc = urllib.parse.quote(SITE, safe="")
    return api(
        f"https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",
        access,
        method="POST",
        data=json.dumps(body).encode(),
    )


def main() -> int:
    access = token()
    enc = urllib.parse.quote(SITE, safe="")
    out: dict = {"site": SITE}

    # Daily last 14d (through latest available)
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=13)
    payload = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["date"],
        "rowLimit": 20,
        "dataState": "all",
    }
    code, data = api(
        f"https://www.googleapis.com/webmasters/v3/sites/{enc}/searchAnalytics/query",
        access,
        method="POST",
        data=json.dumps(payload).encode(),
    )
    out["analytics_http"] = code
    out["analytics_daily"] = []
    if isinstance(data, dict):
        for r in data.get("rows") or []:
            out["analytics_daily"].append(
                {
                    "date": r["keys"][0],
                    "clicks": r.get("clicks"),
                    "impressions": r.get("impressions"),
                    "ctr": round((r.get("ctr") or 0) * 100, 2),
                    "position": round(r.get("position") or 0, 2),
                }
            )

    # Sitemaps summary
    code, sms = api(
        f"https://www.googleapis.com/webmasters/v3/sites/{enc}/sitemaps", access
    )
    out["sitemaps"] = []
    if isinstance(sms, dict):
        for s in sms.get("sitemap") or []:
            out["sitemaps"].append(
                {
                    "path": s.get("path"),
                    "errors": s.get("errors"),
                    "warnings": s.get("warnings"),
                    "lastDownloaded": s.get("lastDownloaded"),
                    "isPending": s.get("isPending"),
                }
            )

    # URL inspection
    out["inspect"] = []
    for u in URLS:
        code, res = inspect(access, u)
        row = {"url": u, "http": code}
        if isinstance(res, dict):
            ir = (res.get("inspectionResult") or {}).get("indexStatusResult") or {}
            rr = (res.get("inspectionResult") or {}).get("richResultsResult") or {}
            row.update(
                {
                    "verdict": ir.get("verdict"),
                    "coverage": ir.get("coverageState"),
                    "lastCrawl": ir.get("lastCrawlTime"),
                    "fetch": ir.get("pageFetchState"),
                    "robots": ir.get("robotsTxtState"),
                    "rich": rr.get("verdict"),
                }
            )
        else:
            row["raw"] = str(res)[:300]
        out["inspect"].append(row)

    # Merchant API: productStatus is integrated in each processed product.
    mid = merchant_id()
    out["merchant_id"] = mid
    out["merchant_api"] = "products/v1"
    counts: Counter = Counter()
    landing_samples = []
    try:
        products = list_products(access, mid)
        out["merchant_http"] = 200
        out["merchant_products"] = len(products)
        for product in products:
            attributes = product.get("productAttributes") or {}
            status = product.get("productStatus") or {}
            for iss in status.get("itemLevelIssues") or []:
                key = f"{issue_servability(iss.get('severity'))}:{iss.get('code')}"
                counts[key] += 1
                if iss.get("code") == "landing_page_error" and len(landing_samples) < 8:
                    landing_samples.append(
                        {
                            "offerId": product.get("offerId"),
                            "title": attributes.get("title"),
                            "link": attributes.get("link"),
                            "desc": iss.get("description"),
                            "detail": iss.get("detail"),
                        }
                    )
    except RuntimeError as error:
        out["merchant_http"] = 0
        out["merchant_error"] = str(error)
    out["merchant_top_issues"] = counts.most_common(15)
    out["landing_page_error_samples"] = landing_samples

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
