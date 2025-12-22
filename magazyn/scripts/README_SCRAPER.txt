============================================================
ALLEGRO SCRAPER - Portable Edition
============================================================

Description:
This scraper bypasses Allegro's DataDome protection by using a real
Chrome browser with a real user session. No headless detection, no
captcha issues (or very rare).

Requirements:
- Windows 10/11
- Python 3.8 or newer
- Chrome browser installed
- Internet connection

Installation:
1. Extract this ZIP to any folder
2. Run SETUP.bat
3. Follow the on-screen instructions

First Run:
1. Run RUN_SCRAPER.bat
2. Chrome will open - LOGIN TO ALLEGRO
3. After login, keep the Chrome window open
4. The scraper API is now running on port 5555

Usage from RPI:
Your RPI can send HTTP requests to check prices:

  GET http://YOUR_PC_IP:5555/check_price?url=<allegro_url>
  
Example:
  curl "http://192.168.31.150:5555/check_price?url=https://allegro.pl/oferta/17892897249"

Response:
  {
    "success": true,
    "price": "159.89",
    "timestamp": "20251221_123456",
    "url": "https://allegro.pl/oferta/17892897249"
  }

If CAPTCHA appears:
  {
    "error": "CAPTCHA detected",
    "message": "Please solve captcha manually in Chrome window and retry"
  }
  
  -> Solve the captcha in Chrome window
  -> Retry your request
  -> It will work

API Endpoints:
  GET  /check_price?url=<url>  - Check Allegro offer price
  GET  /status                 - Check if scraper is running
  POST /restart                - Restart browser (after captcha solve)

Tips:
- Keep Chrome window open (minimized is OK)
- The dedicated profile won't interfere with your daily browsing
- Session cookies are saved - you only login once
- If captcha appears frequently, wait 10-15 minutes between requests

Troubleshooting:
- "Connection refused" -> Run RUN_SCRAPER.bat first
- "CAPTCHA detected" -> Solve manually in Chrome, retry request
- Chrome won't start -> Close any other Chrome instances
- Port 5555 busy -> Change port in scraper_api.py (line 149)

Files:
- scraper_api.py         - Main scraper API server
- SETUP.bat              - Install dependencies
- RUN_SCRAPER.bat        - Start the scraper
- allegro_scraper_profile/ - Chrome profile (created on first run)
- scraped_*.html         - Saved HTML files (for debugging)

Support:
Check the magazyn application logs if integrated with your system.
