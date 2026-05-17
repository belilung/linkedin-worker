@echo off
REM LinkedIn Worker — one-command setup for Windows
echo === LinkedIn Worker Setup ===
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.11+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

echo [OK] Python found

REM Create virtual environment
if not exist "venv" (
    echo [..] Creating virtual environment...
    python -m venv venv
    echo [OK] Virtual environment created
) else (
    echo [OK] Virtual environment already exists
)

REM Activate venv
call venv\Scripts\activate.bat

REM Install package
echo [..] Installing linkedin-worker and dependencies...
pip install -e . --quiet
echo [OK] Package installed

REM Install Playwright browser
echo [..] Installing Chromium browser (this may take a minute)...
playwright install chromium
echo [OK] Chromium installed

REM Create .env if not exists
if not exist ".env" (
    copy .env.example .env >nul
    echo.
    echo [!!] Created .env file. Edit it with your Anthropic API key:
    echo      notepad .env
    echo      Get your key at: https://console.anthropic.com/settings/keys
) else (
    echo [OK] .env already exists
)

REM Create config.yaml if not exists
if not exist "config.yaml" (
    copy config.example.yaml config.yaml >nul
    echo [!!] Created config.yaml from example. Edit it with your campaign settings:
    echo      notepad config.yaml
) else (
    echo [OK] config.yaml already exists
)

REM Create data directories
if not exist "data\cookies" mkdir data\cookies
if not exist "data\screenshots" mkdir data\screenshots

echo.
echo === Setup complete! ===
echo.
echo Next steps:
echo   1. Edit .env         — add your ANTHROPIC_API_KEY
echo   2. Edit config.yaml  — set up your campaign (search_url, context, voice)
echo   3. Activate venv:    venv\Scripts\activate.bat
echo   4. Login:            linkedin-worker login
echo   5. Test:             linkedin-worker connect --dry-run --no-headless
echo   6. Run:              linkedin-worker connect
echo.
pause
