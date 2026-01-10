import requests
import json

url = "https://allegro.pl/oferty-produktu/szelki-dla-psa-truelove-front-line-premium-xl-granatowe-6a3a2dbb-11aa-4922-9bd2-8a1e4840d56d"
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

from bs4 import BeautifulSoup
soup = BeautifulSoup(html, 'html.parser')

for script in soup.find_all('script', type='application/json'):
    text = script.get_text()
    if '__listing_StoreState' in text:
        jdata = json.loads(text)
        items = jdata.get('__listing_StoreState', {}).get('items', {}).get('elements', [])
        
        for item in items:
            seller = item.get('seller', {}).get('login', '')
            if 'helen' in seller.lower() or 'hubu' in seller.lower():
                print(f"\n=== {seller} ===")
                print(f"Full shipping data:")
                print(json.dumps(item.get('shipping', {}), indent=2, ensure_ascii=False))
        break
