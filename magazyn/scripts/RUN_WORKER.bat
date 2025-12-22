@echo off
echo ============================================
echo Allegro Price Scraper Worker
echo ============================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found!
    echo Please install Python 3.8+ from python.org
    pause
    exit /b 1
)

REM Install dependencies if needed
if not exist "venv\" (
    echo Creating virtual environment...
    python -m venv venv
)

echo Activating virtual environment...
call venv\Scripts\activate.bat

echo Installing dependencies...
pip install --quiet selenium webdriver-manager requests

echo.
echo Starting worker...
echo Press Ctrl+C to stop
echo.

REM Start worker - EDIT THIS URL to match your magazyn domain!
python scraper_worker.py --url https://magazyn.retrievershop.pl

pause
