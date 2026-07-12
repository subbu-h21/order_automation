@echo off
echo Starting Order Automation...

:: Build frontend (runs synchronously)
echo Building frontend...
pushd dashboard\frontend
call npm run build
popd

:: Start backend (serves API + built frontend on port 8000)
start "Backend" cmd /k "cd order_automation_v2 && venv\Scripts\activate && python -m uvicorn app:app --app-dir ..\dashboard\backend --port 8000"

:: Open browser once backend is ready
powershell -NoProfile -Command "do { Start-Sleep 1 } until ((Test-NetConnection localhost -Port 8000 -InformationLevel Quiet -WarningAction SilentlyContinue)); Start-Process 'http://localhost:8000'"
