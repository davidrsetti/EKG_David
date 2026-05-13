@echo off
REM ============================================================
REM NEXUS Platform - Start Streamlit UI
REM http://localhost:8501
REM ============================================================

echo.
echo  Starting NEXUS UI on http://localhost:8501
echo  Press Ctrl+C to stop.
echo.

IF NOT EXIST .env (
    echo [WARN] .env not found. Copy .env.example to .env and fill in credentials.
    pause
)

REM Run from the parent of the nexus/ package so imports resolve
cd /d "%~dp0.."
python -m streamlit run nexus\ui\app.py --server.port 8501

IF ERRORLEVEL 1 (
    echo.
    echo [ERROR] UI failed to start. Common fixes:
    echo   - Run setup.bat first
    echo   - Check .env has correct values
    echo.
    pause
)
