@echo off
:: ============================================================
::  Vampiric Crawler — Windows launch script
::  Works from any location, including an external hard drive.
:: ============================================================

setlocal

set "SCRIPT_DIR=%~dp0"

:: ── Find Python ─────────────────────────────────────────────
where python3 >nul 2>&1
if %errorlevel%==0 (
    set PYTHON=python3
) else (
    where python >nul 2>&1
    if %errorlevel%==0 (
        set PYTHON=python
    ) else (
        echo [X] Python not found. Install Python 3.6+ to awaken the vampire.
        pause
        exit /b 1
    )
)

:: ── Install dependencies if needed ──────────────────────────
if exist "%SCRIPT_DIR%requirements.txt" (
    %PYTHON% -m pip install -q -r "%SCRIPT_DIR%requirements.txt" >nul 2>&1
)

:: ── Run ─────────────────────────────────────────────────────
cd /d "%SCRIPT_DIR%"
%PYTHON% vampire.py %*
