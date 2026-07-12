@echo off
echo =============================================
echo   Order Automation - First Time Setup
echo =============================================
echo.

:: Check Python 3.11 is available before doing anything else
py -3.11 -c "print(1)" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.11 was not found via the "py" launcher.
    echo.
    echo This project requires Python 3.11 specifically - newer versions
    echo ^(e.g. 3.13, 3.14^) can be missing prebuilt wheels for Playwright/pandas.
    echo.
    echo Install it from https://www.python.org/downloads/release/python-3110/
    echo ^(make sure the "py launcher" option is checked during install^),
    echo then re-run this script.
    echo.
    pause
    exit /b 1
)

:: Backend / automation engine setup
echo [1/4] Creating Python virtual environment (Python 3.11)...
cd order_automation_v2
py -3.11 -m venv venv

if not exist venv\Scripts\python.exe (
    echo.
    echo ERROR: Virtual environment creation failed - venv\Scripts\python.exe was not created.
    echo Check the output above for the actual error from "py -3.11 -m venv venv".
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
