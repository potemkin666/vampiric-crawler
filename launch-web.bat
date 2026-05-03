@echo off
setlocal EnableExtensions DisableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "APP=%SCRIPT_DIR%webapp.py"

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
            echo [☠] Python not found. Install Python 3.6+ to awaken the crawler console.
            exit /b 1
        )
    )
)

if exist "%SCRIPT_DIR%requirements.txt" (
    %PYTHON% -m pip install -q -r "%SCRIPT_DIR%requirements.txt" >nul 2>&1
)

if not exist "%APP%" (
    echo [☠] Missing web console entrypoint: "%APP%"
    exit /b 1
)

cd /d "%SCRIPT_DIR%"
%PYTHON% "%APP%"
