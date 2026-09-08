@echo off
setlocal
cd /d "%~dp0"
title Bridge Engineering Suite
echo Bridge Engineering Suite v2.0
echo.

rem BES ships its own venv under the current user's LOCALAPPDATA. Launching
rem via plain "python" instead picks up whatever interpreter is first on
rem PATH -- which may be a different install missing packages (reportlab,
rem PyQt6, etc.) even though the dedicated venv has them. Target it
rem explicitly, with a fallback so the app still starts if the venv is
rem ever moved or rebuilt somewhere else.
set "BES_VENV_PY=%LOCALAPPDATA%\BES\venv\Scripts\python.exe"

if exist "%BES_VENV_PY%" (
    "%BES_VENV_PY%" RUN_BES.py
) else (
    echo [Warning] Expected venv python not found at:
    echo   %BES_VENV_PY%
    echo Falling back to system python on PATH - some packages may be missing.
    echo.
    python RUN_BES.py
)

if errorlevel 1 pause
