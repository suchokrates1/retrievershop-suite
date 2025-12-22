@echo off
REM Allegro Scraper Setup
REM Installs everything needed to run the scraper

echo ============================================================
echo Allegro Scraper - Setup
echo ============================================================
echo.
echo This will install:
echo  - Python packages (selenium, flask, webdriver-manager)
echo  - ChromeDriver (automatic)
echo  - Create dedicated Chrome profile for scraping
echo.
pause

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found!
    echo Please install Python 3.8+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo.
echo [1/3] Installing Python packages...
pip install selenium flask webdriver-manager requests

echo.
echo [2/3] Creating dedicated Chrome profile directory...
if not exist "allegro_scraper_profile" mkdir allegro_scraper_profile
echo Profile created: %CD%\allegro_scraper_profile

echo.
echo [3/3] Creating startup script...
(
echo @echo off
echo echo Starting Allegro Scraper API...
echo python scraper_api.py
echo pause
) > RUN_SCRAPER.bat

echo.
echo ============================================================
echo Setup Complete!
echo ============================================================
echo.
echo To start the scraper:
echo  1. Double-click RUN_SCRAPER.bat
echo  2. Login to Allegro in the Chrome window that opens
echo  3. Keep the window running
echo  4. Your RPI can now call: http://YOUR_PC_IP:5555/check_price?url=...
echo.
echo First time: You'll need to login to Allegro manually
echo The session will be saved in the dedicated Chrome profile.
echo.
pause
