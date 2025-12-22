#!/usr/bin/env python3
"""
Cookie sync script - watches for new cookies file from browser export
and syncs it to RPI server.

Usage:
1. Install Cookie-Editor extension in Chrome: https://cookie-editor.com/
2. Export cookies from allegro.pl (JSON format)
3. Save to: C:/Users/sucho/Downloads/allegro_fresh_cookies.json
4. This script will detect new file and upload to RPI

Run: python cookie_watcher.py
"""
import time
import json
import subprocess
import os
from pathlib import Path
from datetime import datetime

WATCH_FILE = Path(r"C:\Users\sucho\Downloads\allegro_fresh_cookies.json")
RPI_HOST = "rpi"
RPI_PATH = "/home/suchokrates1/allegro_cookies.json"
CHECK_INTERVAL = 5  # seconds

last_modified = None

def convert_cookie_format(cookies):
    """Convert Cookie-Editor format to our format"""
    converted = []
    for c in cookies:
        converted.append({
            "name": c.get("name"),
            "value": c.get("value"),
            "domain": c.get("domain", ".allegro.pl"),
            "path": c.get("path", "/"),
            "secure": c.get("secure", False),
            "httpOnly": c.get("httpOnly", False),
            "sameSite": c.get("sameSite", "Lax"),
        })
    return converted

def upload_cookies():
    """Upload cookies to RPI"""
    try:
        # Read and validate
        with open(WATCH_FILE, 'r', encoding='utf-8') as f:
            cookies = json.load(f)
        
        if not isinstance(cookies, list) or len(cookies) == 0:
            print(f"[{datetime.now():%H:%M:%S}] ❌ Invalid cookies format")
            return False
        
        # Convert format if needed
        converted = convert_cookie_format(cookies)
        
        # Save temporarily
        temp_file = Path(r"C:\Users\sucho\Downloads\allegro_cookies_temp.json")
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(converted, f, indent=2)
        
        # Upload to RPI
        result = subprocess.run(
            ['scp', str(temp_file), f"{RPI_HOST}:{RPI_PATH}"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print(f"[{datetime.now():%H:%M:%S}] ✅ Uploaded {len(converted)} cookies to RPI")
            
            # Check for datadome cookie
            datadome = next((c for c in converted if c['name'] == 'datadome'), None)
            if datadome:
                print(f"[{datetime.now():%H:%M:%S}] 🔐 DataDome cookie: {datadome['value'][:50]}...")
            
            temp_file.unlink()
            return True
        else:
            print(f"[{datetime.now():%H:%M:%S}] ❌ Upload failed: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"[{datetime.now():%H:%M:%S}] ❌ Error: {e}")
        return False

def main():
    global last_modified
    
    print("=" * 60)
    print("🍪 Cookie Watcher for Allegro Scraper")
    print("=" * 60)
    print(f"Watching: {WATCH_FILE}")
    print(f"Upload to: {RPI_HOST}:{RPI_PATH}")
    print()
    print("Instructions:")
    print("1. Open https://allegro.pl in Chrome")
    print("2. Click Cookie-Editor extension")
    print("3. Export all cookies → Save as JSON")
    print("4. Save to: C:\\Users\\sucho\\Downloads\\allegro_fresh_cookies.json")
    print("5. Script will auto-upload!")
    print()
    print("Press Ctrl+C to stop")
    print("=" * 60)
    
    # Initial check
    if WATCH_FILE.exists():
        last_modified = WATCH_FILE.stat().st_mtime
        print(f"[{datetime.now():%H:%M:%S}] 📁 Found existing file (modified: {datetime.fromtimestamp(last_modified):%Y-%m-%d %H:%M:%S})")
        print(f"[{datetime.now():%H:%M:%S}] 💡 Save a NEW version to trigger upload")
    else:
        print(f"[{datetime.now():%H:%M:%S}] ⏳ Waiting for cookies file...")
    
    print()
    
    try:
        while True:
            if WATCH_FILE.exists():
                current_modified = WATCH_FILE.stat().st_mtime
                
                if last_modified is None or current_modified > last_modified:
                    print(f"[{datetime.now():%H:%M:%S}] 🔄 New cookies detected! Uploading...")
                    
                    if upload_cookies():
                        last_modified = current_modified
                        print(f"[{datetime.now():%H:%M:%S}] ✨ Done! Watching for next update...")
                    
                    print()
            
            time.sleep(CHECK_INTERVAL)
            
    except KeyboardInterrupt:
        print(f"\n[{datetime.now():%H:%M:%S}] 👋 Stopped")

if __name__ == "__main__":
    main()
