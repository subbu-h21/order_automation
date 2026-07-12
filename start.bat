@echo off
echo Starting Order Automation...

if not exist order_automation_v2\venv\Scripts\python.exe (
    echo.
    echo ERROR: Python virtual environment not found at order_automation_v2\venv
    echo Run setup.bat first.
    echo.
    pause
    exit /b 1
)

if not exist dashboard\frontend\node_modules (
    echo.
    echo ERROR: Frontend dependencies not found at dashboard\frontend\node_modules
    echo Run setup.bat first.
    echo.
    pause
    exit /b 1
)

:: Build frontend (runs synchronously)
echo Building frontend...
pushd dashboard\frontend
call npm run build
if errorlevel 1 (
    popd
    echo.
    echo ERROR: Frontend build failed. See the output above for details.
    echo.
    pause
    exit /b 1
)
popd

:: Start backend (serves API + built frontend on port 8000)
start "Backend" cmd /k "cd order_automation_v2 && venv\Scripts\activate && python -m uvicorn app:app --app-dir ..\dashboard\backend --port 8000"

:: Open browser once backend is ready
powershell -NoProfile -Command "do { Start-Sleep 1 } until ((Test-NetConnection localhost -Port 8000 -InformationLevel Quiet -WarningAction SilentlyContinue)); Start-Process 'http://localhost:8000'"
