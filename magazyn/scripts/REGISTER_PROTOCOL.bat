@echo off
echo ============================================
echo Rejestracja protokolu allegro-scraper://
echo ============================================
echo.

REM Get current directory
set SCRIPT_DIR=%~dp0

REM Create registry entries for custom URL protocol
echo Rejestrowanie protokolu w Windows Registry...

reg add "HKCU\Software\Classes\allegro-scraper" /ve /d "URL:Allegro Scraper Protocol" /f
reg add "HKCU\Software\Classes\allegro-scraper" /v "URL Protocol" /d "" /f
reg add "HKCU\Software\Classes\allegro-scraper\DefaultIcon" /ve /d "%SCRIPT_DIR%scraper_worker.py,0" /f
reg add "HKCU\Software\Classes\allegro-scraper\shell\open\command" /ve /d "\"%SCRIPT_DIR%LAUNCH_WORKER.bat\" \"%%1\"" /f

echo.
echo ✓ Protokol zarejestrowany!
echo.
echo Teraz możesz klikać linki allegro-scraper:// na stronie magazynu
echo Worker uruchomi się automatycznie.
echo.
pause
