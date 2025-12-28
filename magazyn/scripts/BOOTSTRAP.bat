@echo off
REM ============================================
REM Allegro Scraper - Full Bootstrap Installer
REM Auto-installs Python, Chrome, and all dependencies
REM ============================================

setlocal enabledelayedexpansion

echo.
echo ============================================
echo Allegro Price Scraper - Bootstrap
echo ============================================
echo.
echo Checking system requirements...
echo.

REM ============================================
REM Step 1: Check/Install Python
REM ============================================
echo [1/5] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo Python not found! Installing Python...
    
    REM Download Python installer
    echo Downloading Python 3.12...
    powershell -Command "& {Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.0/python-3.12.0-amd64.exe' -OutFile '%TEMP%\python_installer.exe'}"
    
    if not exist "%TEMP%\python_installer.exe" (
        echo ERROR: Failed to download Python installer
        echo Please download manually from https://www.python.org/downloads/
        pause
        exit /b 1
    )
    
    echo Installing Python (this may take a few minutes)...
    "%TEMP%\python_installer.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
    
    REM Wait for installation to complete
    timeout /t 10 /nobreak >nul
    
    REM Refresh PATH
    call RefreshEnv.cmd 2>nul
    
    REM Check again
    python --version >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Python installation failed
        echo Please install Python manually from https://www.python.org/downloads/
        pause
        exit /b 1
    )
    
    echo Python installed successfully!
    del "%TEMP%\python_installer.exe" 2>nul
) else (
    for /f "tokens=*" %%i in ('python --version') do set PYTHON_VERSION=%%i
    echo Found: !PYTHON_VERSION!
)

REM ============================================
REM Step 2: Check Chrome Installation
REM ============================================
echo.
echo [2/5] Detecting Chrome installation...

set CHROME_PATH=
set CHROME_FOUND=0

REM Check common Chrome locations
set "LOCATIONS[0]=C:\Program Files\Google\Chrome\Application\chrome.exe"
set "LOCATIONS[1]=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
set "LOCATIONS[2]=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
set "LOCATIONS[3]=%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"
set "LOCATIONS[4]=%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"

REM Check user-specific paths (like C:\Users\sucho\...)
for /d %%U in (C:\Users\*) do (
    if exist "%%U\AppData\Local\Google\Chrome\Application\chrome.exe" (
        set "CHROME_PATH=%%U\AppData\Local\Google\Chrome\Application\chrome.exe"
        set CHROME_FOUND=1
        goto :chrome_found
    )
)

REM Check standard locations
for /L %%i in (0,1,4) do (
    if exist "!LOCATIONS[%%i]!" (
        set "CHROME_PATH=!LOCATIONS[%%i]!"
        set CHROME_FOUND=1
        goto :chrome_found
    )
)

:chrome_found
if !CHROME_FOUND!==1 (
    echo Found Chrome: !CHROME_PATH!
    
    REM Save Chrome path to config file for scraper to use
    echo CHROME_BINARY=!CHROME_PATH! > chrome_config.txt
) else (
    echo WARNING: Chrome not found in standard locations
    echo The scraper will attempt to use system default Chrome
    echo If scraper fails, please install Chrome from:
    echo https://www.google.com/chrome/
    echo.
)

REM ============================================
REM Step 3: Create/Activate Virtual Environment
REM ============================================
echo.
echo [3/5] Setting up Python virtual environment...

if not exist "venv\" (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment
        pause
        exit /b 1
    )
    echo Virtual environment created!
) else (
    echo Virtual environment already exists
)

echo Activating virtual environment...
call venv\Scripts\activate.bat

REM ============================================
REM Step 4: Install Python Dependencies
REM ============================================
echo.
echo [4/5] Installing Python dependencies...
echo (This may take a few minutes on first run)
echo.

REM Upgrade pip first
python -m pip install --upgrade pip --quiet

REM Install all required packages
pip install --quiet selenium webdriver-manager requests undetected-chromedriver flask

if errorlevel 1 (
    echo WARNING: Some packages may have failed to install
    echo Attempting to install one by one...
    pip install selenium
    pip install webdriver-manager
    pip install requests
    pip install undetected-chromedriver
    pip install flask
)

echo Python packages installed successfully!

REM ============================================
REM Step 5: Create Chrome Profile Directory
REM ============================================
echo.
echo [5/5] Setting up Chrome profile...

if not exist "allegro_scraper_profile" (
    mkdir allegro_scraper_profile
    echo Chrome profile directory created
) else (
    echo Chrome profile directory already exists
)

REM ============================================
REM Bootstrap Complete
REM ============================================
echo.
echo ============================================
echo Bootstrap Complete!
echo ============================================
echo.
echo System is ready to run the Allegro Scraper
echo.
if !CHROME_FOUND!==1 (
    echo Chrome detected: !CHROME_PATH!
) else (
    echo Chrome: Will use system default
)
echo Python: Installed
echo Virtual Environment: Ready
echo Dependencies: Installed
echo.
echo To start the scraper, run: RUN_WORKER.bat
echo.

pause
