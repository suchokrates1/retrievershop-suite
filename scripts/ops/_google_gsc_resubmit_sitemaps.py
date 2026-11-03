#!/usr/bin/env python3
"""Resubmit key sitemaps to GSC after cleanup."""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.expanduser("~/infrastructure"))
import bw_get as bw  # noqa: E402

ITEM = "Google OAuth Retriever Shop"
SITE = "sc-domain:retrievershop.pl"
SITEMAPS = [
    "https://retrievershop.pl/sitemap.xml",
    "https://retrievershop.pl/wp-sitemap.xml",
    "https://retrievershop.pl/page-sitemap.xml",
    "https://retrievershop.pl/post-sitemap.xml",
    "https://retrievershop.pl/product-sitemap.xml",
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


def main() -> int:
    access = token()
    enc = urllib.parse.quote(SITE, safe="")
    for sm in SITEMAPS:
        penc = urllib.parse.quote(sm, safe="")
        url = f"https://www.googleapis.com/webmasters/v3/sites/{enc}/sitemaps/{penc}"
        req = urllib.request.Request(
            url,
            data=b"",
            method="PUT",
            headers={"Authorization": f"Bearer {access}", "Content-Length": "0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                print(f"PUT {r.status} {sm}")
        except Exception as e:
            code = getattr(e, "code", "?")
            body = ""
            if hasattr(e, "read"):
                try:
                    body = e.read().decode()[:300]
                except Exception:
                    pass
            print(f"PUT FAIL {code} {sm} {body}")

    # List current
    req = urllib.request.Request(
        f"https://www.googleapis.com/webmasters/v3/sites/{enc}/sitemaps",
        headers={"Authorization": f"Bearer {access}"},
    )
    data = json.loads(urllib.request.urlopen(req).read())
    for s in data.get("sitemap") or []:
        print(
            f"LIST {s.get('path')} err={s.get('errors')} warn={s.get('warnings')} "
            f"last={s.get('lastDownloaded')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
