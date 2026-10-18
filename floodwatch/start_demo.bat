@echo off
setlocal enabledelayedexpansion

:: ========================================================================
:: FloodWatch Offline Demo Launcher (Phase 4B)
:: Starts local FastAPI server, warms up cache, and opens default browser.
:: ========================================================================

:: Virtual environment path variable (configurable)
set VENV=C:\Users\Koushik\farlands\floodnet_data\.venv
set PYTHON=%VENV%\Scripts\python.exe

if not exist "%PYTHON%" (
    echo [ERROR] Python not found in virtual environment: %PYTHON%
    echo Please verify the VENV path variable in start_demo.bat.
    pause
    exit /b 1
)

echo ===================================================================
echo Starting FloodWatch Offline Flood Intrusion System
echo Python: %PYTHON%
echo ===================================================================

:: Ensure FW_PREWARM is set to all so entire dataset is prewarmed
set FW_PREWARM=all

:: Launch Uvicorn in background
start "FloodWatch Server" "%PYTHON%" -m uvicorn src.api:app --host 127.0.0.1 --port 8000

echo Waiting for FloodWatch backend to initialize...
:wait_loop
"%PYTHON%" -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=1).getcode() == 200 else 1)" 2>nul
if errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait_loop
)

echo [OK] Backend is online! Model resident on GPU.
echo Running full cache prewarm (all 202 tiles)...
"%PYTHON%" scripts\prewarm.py all

echo ===================================================================
echo Opening FloodWatch UI in default browser...
echo URL: http://127.0.0.1:8000
echo ===================================================================
start http://127.0.0.1:8000

echo FloodWatch is running. Close this window or server window to stop.
