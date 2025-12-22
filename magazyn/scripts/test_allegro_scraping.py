"""
Quick test to check what Allegro page structure looks like
"""
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
import time
import re

# Setup Chrome
chrome_options = Options()
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
chrome_options.add_experimental_option("useAutomationExtension", False)
chrome_options.add_argument("--start-maximized")

service = ChromeService(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=chrome_options)
driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

# Test with a real EAN
test_ean = "6971818795157"
print(f"Testing EAN: {test_ean}")
print(f"URL: https://allegro.pl/listing?string={test_ean}")
print()

driver.get(f"https://allegro.pl/listing?string={test_ean}")
time.sleep(5)

# Check for CAPTCHA
if "captcha" in driver.page_source.lower() or "datadome" in driver.page_source.lower():
    print("⚠️  CAPTCHA DETECTED! Solve it manually and press Enter...")
    input()
    time.sleep(2)

html = driver.page_source

# Try different patterns
patterns = {
    'JSON price amount': r'"price":{"amount":"([\d.]+)"',
    'Simple JSON price': r'"price":([\d.]+)',
    'Meta itemprop': r'<meta\s+itemprop="price"\s+content="([\d.]+)"',
    'Data-price': r'data-price="([\d.]+)"',
    'Aria-label': r'aria-label="[^"]*?([\d]+[,.][\d]{2})\s*zł"',
    'buyBoxPrice': r'"buyBoxPrice"[^}]*?"amount":"([\d.]+)"',
}

print("Searching for prices with different patterns:")
print("=" * 60)

found_any = False
for name, pattern in patterns.items():
    matches = re.findall(pattern, html)
    if matches:
        print(f"✓ {name}: {matches[:5]}")  # Show first 5
        found_any = True
    else:
        print(f"✗ {name}: No matches")

print()

if not found_any:
    print("No prices found with any pattern!")
    print()
    print("Saving page source to allegro_test_page.html for analysis...")
    with open("allegro_test_page.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("✓ Saved. Check the file to see what Allegro actually returns.")

driver.quit()
