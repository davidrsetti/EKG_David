@echo off
REM ============================================================
REM NEXUS Platform - Windows Setup Script
REM Run this ONCE to set up the environment
REM ============================================================

echo.
echo  ===========================================
echo   NEXUS Platform - Environment Setup
echo  ===========================================
echo.

REM Check Python is available
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo [ERROR] Python not found. Install Python 3.10+ from https://python.org
    echo         Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

echo [OK] Python found:
python --version

REM Check pip
pip --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo [ERROR] pip not found. Re-install Python and ensure pip is included.
    pause
    exit /b 1
)

echo.
echo [STEP 1] Installing Python dependencies...
pip install -r requirements.txt
IF ERRORLEVEL 1 (
    echo [ERROR] Dependency installation failed. Check the error above.
    pause
    exit /b 1
)

echo.
echo [STEP 2] Creating logs directory...
IF NOT EXIST logs mkdir logs
echo [OK] logs\ directory ready.

echo.
echo [STEP 3] Creating .env file from template...
IF NOT EXIST .env (
    copy .env.example .env
    echo [OK] .env created. EDIT IT NOW with your credentials.
) ELSE (
    echo [SKIP] .env already exists. Skipping.
)

echo.
echo  ===========================================
echo   Setup Complete!
echo  ===========================================
echo.
echo  NEXT STEPS:
echo    1. Edit .env with your Stardog + OpenAI credentials
echo    2. Run start_api.bat   to launch the API  (port 8000)
echo    3. Run start_ui.bat    to launch the UI   (port 8501)
echo.
pause
