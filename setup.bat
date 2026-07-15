@echo off
echo =============================================
echo   Order Automation - First Time Setup
echo =============================================
echo.

:: Backend / automation engine setup
echo [1/4] Creating Python virtual environment...
cd order_automation_v2
python -m venv venv

if not exist venv\Scripts\python.exe (
    echo.
    echo ERROR: Virtual environment creation failed - venv\Scripts\python.exe was not created.
    echo Check the output above for the actual error from "python -m venv venv".
    echo Make sure Python 3.11+ is installed and on PATH.
    echo.
    pause
    exit /b 1
)
echo Done.
echo.

echo [2/4] Installing Python dependencies...
call venv\Scripts\activate
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: pip install failed. See the output above for details.
    echo.
    pause
    exit /b 1
)
echo Done.
echo.

echo [3/4] Installing Playwright browser...
playwright install chromium
echo Done.
echo.

:: Create .env if it doesn't exist
if not exist .env (
    copy .env.example .env
    echo Created order_automation_v2\.env from .env.example
    echo.
    echo  IMPORTANT: Open order_automation_v2\.env and fill in your settings before running the app.
    echo  - CRM_USERNAME / CRM_PASSWORD
    echo  - CRM_USERNAME_SHIVAJI_CHOWK / CRM_PASSWORD_SHIVAJI_CHOWK
    echo  - CHROME_PROFILE_DIR
    echo  - SESSION_SECRET_KEY - generate with: python -c "import secrets; print(secrets.token_hex(32))"
    echo  - DASHBOARD_USERS - staff login accounts; generate each one with: python hash_password.py
    echo.
) else (
    echo order_automation_v2\.env already exists, skipping.
    echo.
)

cd ..

:: Frontend setup
echo [4/4] Installing frontend dependencies...
where npm >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: "npm" was not found on PATH.
    echo Install Node.js 18+ from https://nodejs.org then re-run this script.
    echo.
    pause
    exit /b 1
)

cd dashboard\frontend
call npm install
if errorlevel 1 (
    echo.
    echo ERROR: npm install failed. See the output above for details.
    echo.
    pause
    exit /b 1
)
cd ..\..
echo Done.
echo.

echo =============================================
echo   Setup complete!
echo.
echo   Next steps:
echo   1. Edit order_automation_v2\.env with your settings (if just created)
echo   2. Double-click start.bat to run the app
echo =============================================
pause
