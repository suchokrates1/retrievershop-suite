import requests
import json
import re

# STRONA POROWNANIA PRODUKTOW - tu sa dane!
url = "https://allegro.pl/oferty-produktu/szelki-dla-psa-truelove-front-line-premium-xl-granatowe-6a3a2dbb-11aa-4922-9bd2-8a1e4840d56d"
token = "2TlFTbxoi626KAue012cce364011c0e7d24a364eed6e9f6ae"

print(f"[LOG] URL: {url}")

query = '''mutation { 
    goto(url: "''' + url + '''", waitUntil: networkIdle, timeout: 60000) { status } 
    solve { found solved }
    html { html } 
}'''

r = requests.post(f"https://production-sfo.browserless.io/stealth/bql?token={token}&proxy=residential", 
    json={"query": query}, timeout=180)

data = r.json()
html = data.get("data", {}).get("html", {}).get("html", "")
page_status = data.get("data", {}).get("goto", {}).get("status")

print(f"[LOG] Page status: {page_status}")
print(f"[LOG] HTML: {len(html)} bytes")
print(f"[LOG] Has listing: {'__listing_StoreState' in html}")

if "__listing_StoreState" in html:
    print("[LOG] SUKCES! Parsuje oferty...")
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    for script in soup.find_all('script', type='application/json'):
        text = script.get_text()
        if '__listing_StoreState' in text:
            jdata = json.loads(text)
            items = jdata.get('__listing_StoreState', {}).get('items', {}).get('elements', [])
            print(f"[LOG] Found {len(items)} offers!")
            for item in items:
                seller = item.get('seller', {}).get('login', '?')
                price = item.get('price', {}).get('mainPrice', {}).get('amount', '?')
                shipping = item.get('shipping', {}).get('summary', {}).get('labels', [])
                delivery = ''
                for l in shipping:
                    if 'dostawa' in l.get('text', '').lower():
                        delivery = l.get('text', '')
                        break
                print(f"  - {seller}: {price} PLN | {delivery}")
            break
else:
    title = re.search(r'<title>([^<]+)</title>', html)
    print(f"[LOG] Title: {title.group(1)[:60] if title else 'NO TITLE'}")
    print(f"[LOG] DataDome: {'captcha-delivery' in html}")
