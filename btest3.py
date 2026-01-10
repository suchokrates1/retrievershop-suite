import requests
import json
import re

url = "https://allegro.pl/oferta/szelki-dla-psa-truelove-front-line-premium-xl-granatowe-18180401323"
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

# Tytul
title = re.search(r'<title>([^<]+)</title>', html)
print(f"Title: {title.group(1)[:80] if title else 'NO TITLE'}")

# Sprawdz co mamy
print(f"Has listing: {'__listing_StoreState' in html}")
print(f"Has inne-oferty: {'inne-oferty' in html}")

# Zapisz
with open("/tmp/allegro_page.html", "w") as f:
    f.write(html)
print("Saved to /tmp/allegro_page.html")

# Szukaj linku do porownania produktow
match = re.search(r'href="(/oferty-produktu/[^"]+)"', html)
if match:
    print(f"Found product comparison link: {match.group(1)}")
