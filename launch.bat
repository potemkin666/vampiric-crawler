@echo off
:: ============================================================
::  Vampiric Crawler — Windows launch script
::  Works from any location, including an external hard drive.
:: ============================================================

setlocal

set "SCRIPT_DIR=%~dp0"
set "APP=%SCRIPT_DIR%vampire.py"

:: ── Find Python ─────────────────────────────────────────────
where python3 >nul 2>&1
if %errorlevel%==0 (
    set PYTHON=python3
) else (
    where python >nul 2>&1
    if %errorlevel%==0 (
        set PYTHON=python
    ) else (
        py -3 -c "import sys" >nul 2>&1
        if %errorlevel%==0 (
            set PYTHON=py -3
        ) else (
            echo [☠] Python not found. Install Python 3.6+ to awaken the vampire.
            pause
            exit /b 1
        )
    )
)

:: ── Install dependencies if needed ──────────────────────────
if exist "%SCRIPT_DIR%requirements.txt" (
    %PYTHON% -m pip install -q -r "%SCRIPT_DIR%requirements.txt" >nul 2>&1
)

:: ── Ensure the entrypoint exists ────────────────────────────
if not exist "%APP%" (
    echo [☠] Missing entrypoint: "%APP%"
    pause
    exit /b 1
)

:: ── Run ─────────────────────────────────────────────────────
cd /d "%SCRIPT_DIR%"
if "%~1"=="" (
    echo.
    set /p TARGET_URL=Enter target URL (for example https://example.com): 
    for /f "tokens=* delims= " %%A in ("%TARGET_URL%") do set "TARGET_URL=%%A"
    if not defined TARGET_URL (
        echo [☠] No prey specified. Closing the coffin.
        pause
        exit /b 1
    )
    %PYTHON% "%APP%" -u "%TARGET_URL%"
) else (
    %PYTHON% "%APP%" %*
)

set "EXITCODE=%errorlevel%"
if not "%EXITCODE%"=="0" (
    pause
)
exit /b %EXITCODE%
