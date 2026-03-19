@echo off
REM ─────────────────────────────────────────────────────────────────
REM  Trading Bot — Windows launcher
REM  Double-click this file OR call it from any CMD/PowerShell window
REM ─────────────────────────────────────────────────────────────────

cd /d "%~dp0"

REM ── Activate virtual environment if it exists ──────────────────
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo [OK] Virtual environment activated.
) else (
    echo [WARN] No venv found. Using system Python.
)

REM ── Check Python is available ──────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] Python not found on PATH.
    echo         Install Python 3.11 from https://www.python.org/downloads/
    echo         Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

echo.
echo Choose an action:
echo   1  Pre-flight smoke test  (test_run.py)
echo   2  Start bot              (main.py)
echo   3  Exit
echo.
set /p choice="Enter 1, 2 or 3: "

if "%choice%"=="1" (
    echo.
    echo Running pre-flight test...
    python test_run.py
    pause
) else if "%choice%"=="2" (
    echo.
    echo Starting Trading Bot (Ctrl+C to stop)...
    python main.py
    pause
) else (
    exit /b 0
)
