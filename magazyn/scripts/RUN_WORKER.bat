@echo off
REM ============================================
REM Allegro Price Scraper Worker - Smart Launcher
REM Auto-configures and starts the scraper
REM ============================================

setlocal enabledelayedexpansion

echo.
echo ============================================
echo Allegro Price Scraper Worker
echo ============================================
echo.

REM Check if first time setup is needed
if not exist "venv\" (
    if not exist "allegro_scraper_profile\" (
        echo First time setup detected!
        echo Running bootstrap installer...
        echo.
        call BOOTSTRAP.bat
        if errorlevel 1 (
            echo Bootstrap failed! Cannot continue.
            pause
            exit /b 1
        )
    )
)

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found!
    echo.
    echo Running bootstrap installer to install Python...
    call BOOTSTRAP.bat
    if errorlevel 1 (
        echo Failed to install Python
        echo Please download and install manually from:
        echo https://www.python.org/downloads/
        pause
        exit /b 1
    )
)

REM Create virtual environment if missing
if not exist "venv\" (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment
        pause
        exit /b 1
    )
)

REM Activate virtual environment
echo Activating virtual environment...
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else (
    echo ERROR: Virtual environment not properly configured
    echo Try deleting 'venv' folder and running again
    pause
    exit /b 1
)

REM Auto-install/update dependencies quietly
echo Checking dependencies...
pip install --quiet --upgrade pip 2>nul
pip install --quiet selenium webdriver-manager requests undetected-chromedriver flask 2>nul

if errorlevel 1 (
    echo Installing dependencies (this may take a moment)...
    pip install selenium webdriver-manager requests undetected-chromedriver flask
)

REM Create profile directory if missing
if not exist "allegro_scraper_profile" (
    mkdir allegro_scraper_profile
)

echo.
echo ======================================================================
echo Allegro Competitor Price Checker
echo ======================================================================
echo Magazyn URL: https://magazyn.retrievershop.pl
echo.
echo Worker started! Leave this window open.
echo Press Ctrl+C to stop the worker.
echo.
echo ======================================================================
echo.

REM Start worker - scraper will auto-detect Chrome location
python scraper_worker.py --url https://magazyn.retrievershop.pl

REM If error, show troubleshooting
if errorlevel 1 (
    echo.
    echo ======================================================================
    echo Worker stopped with error
    echo ======================================================================
    echo.
    echo Troubleshooting:
    echo 1. Make sure Chrome is installed
    echo 2. Try running BOOTSTRAP.bat for automatic setup
    echo 3. Check that https://magazyn.retrievershop.pl is accessible
    echo 4. Make sure you are logged into Allegro in your default Chrome
    echo.
)

pause
