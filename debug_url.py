import requests
import re

url = "https://allegro.pl/oferta/szelki-dla-psa-truelove-front-line-premium-xl-czarne-18180425025"
token = "2TlFTbxoi626KAue012cce364011c0e7d24a364eed6e9f6ae"

query = '''mutation { 
    goto(url: "''' + url + '''", waitUntil: networkIdle, timeout: 60000) { status url } 
    solve { found solved }
    html { html } 
}'''

r = requests.post(f"https://production-sfo.browserless.io/stealth/bql?token={token}&proxy=residential", 
    json={"query": query}, timeout=180)

data = r.json()
goto = data.get("data", {}).get("goto", {})
html = data.get("data", {}).get("html", {}).get("html", "")

print(f"Requested URL: {url}")
print(f"Final URL: {goto.get('url')}")
print(f"Status: {goto.get('status')}")
print(f"HTML: {len(html)} bytes")

# Title
title = re.search(r'<title>([^<]+)</title>', html)
print(f"Title: {title.group(1)[:80] if title else 'NO TITLE'}")
