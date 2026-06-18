@echo off
cd /d "%~dp0"

echo iiSU CN Scraper
echo.

where py >nul 2>&1 && set "PY=py" || set "PY=python"

%PY% --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python not found. Install Python 3.10+
    echo https://www.python.org/downloads/
    pause
    exit /b
)

%PY% -c "import flet" >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing dependencies...
    %PY% -m pip install -r requirements.txt
    echo.
)

echo Starting iiSU...
%PY% main.py

pause
