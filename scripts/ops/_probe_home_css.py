#!/usr/bin/env python3
import re
import sys
import urllib.request

url = sys.argv[1] if len(sys.argv) > 1 else "https://retrievershop.pl/"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 RS-CSS-Probe", "Cache-Control": "no-cache"})
with urllib.request.urlopen(req, timeout=30) as r:
    html = r.read().decode("utf-8", "replace")
    final = r.geturl()
    code = r.status

print(f"url={final} code={code} len={len(html)}")
m = re.search(r"<title>([^<]+)", html, re.I)
print("title=", m.group(1) if m else None)
bm = re.search(r'<body[^>]*class="([^"]+)"', html, re.I)
print("body=", (bm.group(1)[:220] if bm else None))

links = re.findall(r'<link[^>]+>', html, re.I)
sheets = [l for l in links if re.search(r"rel=['\"]stylesheet['\"]", l, re.I)]
print("stylesheets=", len(sheets))
hrefs = []
for l in sheets:
    hm = re.search(r"href=['\"]([^'\"]+)", l, re.I)
    if hm:
        hrefs.append(hm.group(1))
        print(" ", hm.group(1)[:160])

print("style_ids=", re.findall(r'<style[^>]*id=[\'"]([^\'"]+)', html, re.I)[:40])
for needle in [
    "rs-ui-bg",
    "id=\"rs-",
    "retriever-ui",
    "elementor-post-",
    "elementor-frontend",
    "ct-main-styles",
    "blocksy",
    "seraph-accel",
    "data-lzl-src",
    "wp-block-library",
]:
    print(f"{needle}:", "yes" if needle in html else "NO")

# check first N css urls
print("--- css fetch ---")
ok = fail = 0
for href in hrefs[:20]:
    if href.startswith("//"):
        href = "https:" + href
    elif href.startswith("/"):
        href = "https://retrievershop.pl" + href
    try:
        rq = urllib.request.Request(href, headers={"User-Agent": "Mozilla/5.0 RS-CSS-Probe"})
        with urllib.request.urlopen(rq, timeout=20) as rr:
            body = rr.read()
            ctype = rr.headers.get("Content-Type", "")
            print(f"OK {rr.status} {len(body):6d} {ctype[:40]:40s} {href[:100]}")
            ok += 1
            if b"{" not in body[:500] and b"@" not in body[:200] and len(body) < 50:
                print("  WARN: tiny/non-css body", body[:80])
    except Exception as e:
        print(f"FAIL {href[:100]} :: {e}")
        fail += 1
print(f"summary ok={ok} fail={fail}")

# look for empty/missing critical inline
if "elementor-post-7" not in html and "elementor-post-" not in html:
    print("WARN: no elementor-post-* css link in HTML")
if "ct-main-styles" not in html and "blocksy" not in html.lower():
    print("WARN: blocksy main styles missing from HTML")
