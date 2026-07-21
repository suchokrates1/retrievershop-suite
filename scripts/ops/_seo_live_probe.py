#!/usr/bin/env python3
"""Live HTML SEO probe for retrievershop.pl."""
from __future__ import annotations

import http.client
import re
import urllib.request
from urllib.parse import urlparse

UA = {"User-Agent": "Mozilla/5.0 SEO-Audit"}


def fetch(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode("utf-8", "replace")


def grab(html: str, pat: str) -> str:
    m = re.search(pat, html, re.I | re.S)
    return (m.group(1).strip() if m else "")[:240]


def main() -> None:
    urls = [
        "https://retrievershop.pl/",
        "https://retrievershop.pl/produkty/",
        "https://retrievershop.pl/kontakt/",
        "https://retrievershop.pl/produkt/szelki-dla-psa-truelove-front-line-premium-czarne/",
        "https://retrievershop.pl/o-nas/",
    ]
    for u in urls:
        code, html = fetch(u)
        title = grab(html, r"<title[^>]*>(.*?)</title>")
        desc = grab(html, r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']')
        if not desc:
            desc = grab(html, r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']')
        og = grab(html, r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](.*?)["\']')
        if not og:
            og = grab(html, r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:image["\']')
        can = grab(html, r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\'](.*?)["\']')
        robots = grab(html, r'<meta[^>]+name=["\']robots["\'][^>]+content=["\'](.*?)["\']')
        phones = sorted(
            set(
                re.findall(
                    r"(?:\+48)?[\s\-]*(?:782[\s\-]*865[\s\-]*895|605[\s\-]*864[\s\-]*663)",
                    html,
                )
            )
        )
        ld = len(re.findall(r"application/ld\+json", html, re.I))
        h1 = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
        h1 = [re.sub(r"<[^>]+>", "", x).strip() for x in h1][:3]
        old_phone = bool(re.search(r"605[\s\-]*864[\s\-]*663|\+48605864663", html))
        print("---", u, "HTTP", code)
        print("title:", title)
        print("desc:", desc)
        print("canonical:", can)
        print("robots:", robots)
        print("og:image:", og)
        print("ld+json blocks:", ld)
        print("h1:", h1)
        print("phones:", phones)
        print("old_phone_present:", old_phone)

    for u in [
        "https://retrievershop.pl/robots.txt",
        "https://retrievershop.pl/sitemap.xml",
    ]:
        _, body = fetch(u)
        print("===", u, "len", len(body))
        print(body[:900])

    u = "https://retrievershop.pl/produkt/szelki-dla-psa-trelove-front-line-premium-xs-czarne/"
    for _ in range(5):
        p = urlparse(u)
        conn = http.client.HTTPSConnection(p.netloc, timeout=20)
        path = p.path + (("?" + p.query) if p.query else "")
        conn.request("GET", path, headers={"User-Agent": "SEO"})
        resp = conn.getresponse()
        loc = resp.getheader("Location")
        print("redir", resp.status, u, "->", loc)
        if resp.status not in (301, 302, 303, 307, 308) or not loc:
            break
        if loc.startswith("/"):
            u = f"{p.scheme}://{p.netloc}{loc}"
        else:
            u = loc


if __name__ == "__main__":
    main()
