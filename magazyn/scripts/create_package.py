#!/usr/bin/env python3
"""
Allegro Scraper - Package Creator
Creates a portable ZIP package with everything needed to run the scraper
"""
import zipfile
import shutil
from pathlib import Path

def create_package():
    """Create portable scraper package"""
    
    # Files to include
    files = [
        "scraper_api.py",
        "SETUP.bat",
        "README_SCRAPER.txt"
    ]
    
    package_name = "AllegroScraper_Portable.zip"
    
    print("Creating portable scraper package...")
    
    with zipfile.ZipFile(package_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file in files:
            if Path(file).exists():
                zipf.write(file, f"AllegroScraper/{file}")
                print(f"  Added: {file}")
            else:
                print(f"  WARNING: {file} not found, skipping")
    
    size_mb = Path(package_name).stat().st_size / 1024 / 1024
    print(f"\n✓ Package created: {package_name} ({size_mb:.2f} MB)")
    print(f"\nTo use on another computer:")
    print(f"  1. Copy {package_name} to target PC")
    print(f"  2. Extract ZIP")
    print(f"  3. Run SETUP.bat")
    print(f"  4. Run RUN_SCRAPER.bat")
    
    return package_name

if __name__ == "__main__":
    create_package()
