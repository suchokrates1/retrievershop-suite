@echo off
REM This script is called by Windows when you click allegro-scraper:// links

echo ============================================
echo Uruchamianie Allegro Scraper Worker
echo ============================================
echo.

REM Get script directory
cd /d "%~dp0"

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found!
    echo Please install Python 3.8+ from python.org
    pause
    exit /b 1
)

REM Create virtual environment if needed
if not exist "venv\" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate and install dependencies
call venv\Scripts\activate.bat
pip install --quiet selenium webdriver-manager requests

REM Start worker
echo.
echo Worker started! Leave this window open.
echo Press Ctrl+C to stop the worker.
echo.

python scraper_worker.py --url https://magazyn.retrievershop.pl --interval 30

pause
