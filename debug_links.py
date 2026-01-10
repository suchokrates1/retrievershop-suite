import requests
import re

url = "https://allegro.pl/oferta/szelki-dla-psa-truelove-front-line-premium-xl-czarne-18180425025"
token = "2TlFTbxoi626KAue012cce364011c0e7d24a364eed6e9f6ae"

query = '''mutation { 
    goto(url: "''' + url + '''", waitUntil: networkIdle, timeout: 60000) { status } 
    solve { found solved }
    html { html } 
}'''

r = requests.post(f"https://production-sfo.browserless.io/stealth/bql?token={token}&proxy=residential", 
    json={"query": query}, timeout=180)

data = r.json()
html = data.get("data", {}).get("html", {}).get("html", "")

print(f"HTML: {len(html)} bytes")
print(f"Has DataDome: {'captcha-delivery' in html}")

# Szukam wszystkich linków /oferty-produktu/
matches = re.findall(r'/oferty-produktu/([^"\'<>\s]+)', html)
print(f"Found {len(matches)} oferty-produktu links:")
for m in list(set(matches))[:10]:
    print(f"  - {m[:80]}")

# Czy jest szelki?
szelki = [m for m in matches if 'szelki' in m.lower()]
print(f"\nSzelki matches: {szelki}")

# Title
title = re.search(r'<title>([^<]+)</title>', html)
print(f"\nTitle: {title.group(1)[:80] if title else 'NO TITLE'}")
