@echo off
echo =============================================
echo   Order Automation - First Time Setup
echo =============================================
echo.

:: Backend / automation engine setup
:: Uses Python 3.11 specifically (via the py launcher) - newer versions
:: (e.g. 3.14) may lack prebuilt wheels for Playwright/pandas.
echo [1/4] Creating Python virtual environment (Python 3.11)...
cd order_automation_v2
py -3.11 -m venv venv
echo Done.
echo.

echo [2/4] Installing Python dependencies...
call venv\Scripts\activate
pip install -r requirements.txt
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
cd dashboard\frontend
call npm install
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
