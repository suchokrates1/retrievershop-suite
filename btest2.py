import requests
import json

url = "https://allegro.pl/oferta/szelki-dla-psa-truelove-front-line-premium-xl-granatowe-18180401323"
token = "2TlFTbxoi626KAue012cce364011c0e7d24a364eed6e9f6ae"

# Z solve dla CAPTCHA
query = '''mutation { 
    goto(url: "''' + url + '''", waitUntil: networkIdle, timeout: 60000) { status } 
    solve { found solved }
    html { html } 
}'''

r = requests.post(f"https://production-sfo.browserless.io/stealth/bql?token={token}&proxy=residential", 
    json={"query": query}, timeout=180)

print(f"Status: {r.status_code}")
data = r.json()

if "errors" in data:
    print(f"Errors: {data['errors']}")
    
solve = data.get("data", {}).get("solve", {})
print(f"CAPTCHA found: {solve.get('found')}, solved: {solve.get('solved')}")

html = data.get("data", {}).get("html", {}).get("html", "")
page_status = data.get("data", {}).get("goto", {}).get("status")
print(f"Page status: {page_status}")
print(f"HTML: {len(html)} bytes")
has_listing = "__listing_StoreState" in html
has_datadome = "captcha-delivery" in html
print(f"Has listing: {has_listing}")
print(f"DataDome: {has_datadome}")

if has_listing:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    for script in soup.find_all('script', type='application/json'):
        if '__listing_StoreState' in script.get_text():
            jdata = json.loads(script.get_text())
            items = jdata.get('__listing_StoreState', {}).get('items', {}).get('elements', [])
            print(f"Found {len(items)} offers!")
            for item in items[:5]:
                seller = item.get('seller', {}).get('login', '?')
                price = item.get('price', {}).get('mainPrice', {}).get('amount', '?')
                print(f"  - {seller}: {price} PLN")
            break
