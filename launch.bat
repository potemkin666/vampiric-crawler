@echo off
:: ============================================================
::  Vampiric Crawler — Windows launch script
::  Works from any location, including an external hard drive.
:: ============================================================

setlocal EnableExtensions DisableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "APP=%SCRIPT_DIR%vampire.py"
set "INTERACTIVE_LAUNCH="

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
            if "%~1"=="" pause
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
    if "%~1"=="" pause
    exit /b 1
)

:: ── First-run diagnostics ───────────────────────────────────
%PYTHON% "%APP%" --setup-check -o "%SCRIPT_DIR%"
if errorlevel 1 (
    echo [!] First-run diagnostics found issues. Review the output above before continuing.
)

:: ── Run ─────────────────────────────────────────────────────
cd /d "%SCRIPT_DIR%"
if "%~1"=="" (
    set "INTERACTIVE_LAUNCH=1"
    echo.
    echo [BAT] Double-click mode detected.
    echo [BAT] Paste the full target URL below, then press Enter to start the crawl.
    echo [BAT] Example: https://example.com
    echo.
    set /p TARGET_URL=Target URL: 
    call :trim_variable TARGET_URL
    if not defined TARGET_URL (
        echo [☠] No prey specified. Closing the coffin.
        echo [BAT] Press any key to close this window.
        pause >nul
        exit /b 1
    )
    echo.
    echo [BAT] Launching crawl against "%TARGET_URL%"...
    %PYTHON% "%APP%" -u "%TARGET_URL%"
) else (
    %PYTHON% "%APP%" %*
)

set "EXITCODE=%errorlevel%"
if defined INTERACTIVE_LAUNCH (
    echo.
    if "%EXITCODE%"=="0" (
        echo [BAT] Crawl finished. Press any key to close this window.
    ) else (
        echo [☠] Crawl failed with exit code %EXITCODE%. Press any key to close this window.
    )
    pause >nul
)
exit /b %EXITCODE%

:trim_variable
setlocal EnableDelayedExpansion
set "value=!%~1!"
for /f "tokens=* delims= " %%A in ("!value!") do set "value=%%A"
:trim_trailing_spaces
if defined value if "!value:~-1!"==" " (
    set "value=!value:~0,-1!"
    goto trim_trailing_spaces
)
endlocal & set "%~1=%value%"
exit /b
