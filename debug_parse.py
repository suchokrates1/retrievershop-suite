import requests
import json
import re
from datetime import datetime

MONTHS_PL = {
    'sty': 1, 'lut': 2, 'mar': 3, 'kwi': 4, 'maj': 5, 'cze': 6,
    'lip': 7, 'sie': 8, 'wrz': 9, 'paz': 10, 'paź': 10, 'lis': 11, 'gru': 12
}

def parse_delivery_days(delivery_text, today=None):
    if today is None:
        today = datetime.now()
    
    text = delivery_text.lower()
    
    # Check for "dostawa za X – Y dni" (Chinese sellers!)
    match = re.search(r'dostawa\s+za\s+(\d+)\s*[–-]\s*(\d+)\s*dni', text)
    if match:
        min_days = int(match.group(1))
        max_days = int(match.group(2))
        return (min_days + max_days) // 2
    
    # Check for "dostawa za X dni"
    match = re.search(r'dostawa\s+za\s+(\d+)\s*dni', text)
    if match:
        return int(match.group(1))
    
    # Check for specific date like "14 sty"
    text_clean = text.replace('ź', 'z').replace('ó', 'o')
    match = re.search(r'(\d{1,2})\s+(sty|lut|mar|kwi|maj|cze|lip|sie|wrz|paz|lis|gru)', text_clean)
    if match:
        day = int(match.group(1))
        month = MONTHS_PL.get(match.group(2), 1)
        year = today.year
        if month < today.month:
            year += 1
        try:
            delivery_date = datetime(year, month, day)
            return (delivery_date - today).days
        except ValueError:
            pass
    
    # Check for day names (Polish)
    day_names = {
        'poniedziałek': 0, 'poniedzialek': 0,
        'wtorek': 1,
        'środa': 2, 'sroda': 2, 'środę': 2, 'srode': 2,
        'czwartek': 3,
        'piątek': 4, 'piatek': 4,
        'sobota': 5, 'sobotę': 5, 'sobote': 5,
        'niedziela': 6, 'niedzielę': 6, 'niedziele': 6
    }
    
    for day_name, day_offset in day_names.items():
        if day_name in text:
            today_weekday = today.weekday()
            days_until = (day_offset - today_weekday) % 7
            if days_until == 0:
                days_until = 7
            return days_until
    
    return None

# Test
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

print(f"Today: {datetime.now()} (weekday={datetime.now().weekday()})")
print()

for script in soup.find_all('script', type='application/json'):
    text = script.get_text()
    if '__listing_StoreState' in text:
        jdata = json.loads(text)
        items = jdata.get('__listing_StoreState', {}).get('items', {}).get('elements', [])
        
        for item in items:
            seller = item.get('seller', {}).get('login', '')
            if not seller:
                continue
            
            shipping = item.get('shipping', {}).get('summary', {}).get('labels', [])
            
            # Same logic as scraper
            delivery_text = ''
            for label in shipping:
                txt = label.get('text', '')
                if 'dostawa od' in txt.lower() and 'zł' in txt.lower():
                    continue
                if 'dostawa' in txt.lower() or 'dni' in txt.lower():
                    delivery_text = txt
                    break
            
            days = parse_delivery_days(delivery_text)
            print(f"{seller:25} | delivery_text: '{delivery_text}' | days: {days}")
        break
