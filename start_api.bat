@echo off
REM ============================================================
REM NEXUS Platform - Start FastAPI Backend
REM http://localhost:8000/docs
REM ============================================================

echo.
echo  Starting NEXUS API on http://localhost:8000
echo  API Docs: http://localhost:8000/docs
echo  Press Ctrl+C to stop.
echo.

IF NOT EXIST .env (
    echo [WARN] .env not found. Copy .env.example to .env and fill in credentials.
    pause
)

REM Run from the parent of the nexus/ package so imports resolve
cd /d "%~dp0.."
python -m uvicorn nexus.api.main:app --reload --port 8000 --host 0.0.0.0

IF ERRORLEVEL 1 (
    echo.
    echo [ERROR] API failed to start. Common fixes:
    echo   - Run setup.bat first
    echo   - Check .env has correct values
    echo   - Make sure port 8000 is not in use
    pause
)
