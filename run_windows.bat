@echo off
setlocal
cd /d "%~dp0"
title Bridge Engineering Suite
echo Bridge Engineering Suite v2.0
echo.

rem ---------------------------------------------------------------------------
rem  Portable launcher.
rem
rem  RUN_BES.py builds its own virtual environment (under %LOCALAPPDATA%\BES)
rem  and installs every dependency on first run, so all this script has to do
rem  is find ANY working Python 3 to bootstrap with. Different PCs install
rem  Python differently, so we probe several locations in order of preference:
rem
rem    1. The BES venv itself (fast path once it exists - no reinstall churn).
rem    2. The Windows "py" launcher  -> most reliable when Python came from
rem       python.org; also dodges the Microsoft Store "python" alias stub.
rem    3. "python" on PATH.
rem    4. "python3" on PATH.
rem
rem  This makes double-clicking the file work on any machine (office, home,
rem  a fresh PC) as long as Python 3.10+ is installed somewhere.
rem ---------------------------------------------------------------------------

set "PYEXE="

rem 1) Existing BES venv (fast path)
set "BES_VENV_PY=%LOCALAPPDATA%\BES\venv\Scripts\python.exe"
if exist "%BES_VENV_PY%" set "PYEXE="%BES_VENV_PY%""

rem 2) Windows Python launcher
if not defined PYEXE (
    py -3 --version >nul 2>&1 && set "PYEXE=py -3"
)

rem 3) python on PATH
if not defined PYEXE (
    python --version >nul 2>&1 && set "PYEXE=python"
)

rem 4) python3 on PATH
if not defined PYEXE (
    python3 --version >nul 2>&1 && set "PYEXE=python3"
)

if not defined PYEXE (
    echo [Error] No Python 3 interpreter was found on this PC.
    echo.
    echo Install Python 3.10 or newer from:
    echo     https://www.python.org/downloads/
    echo.
    echo IMPORTANT: during setup, tick "Add python.exe to PATH".
    echo Then double-click this file again.
    echo.
    pause
    exit /b 1
)

echo Launching with: %PYEXE%
echo (First run on a new PC builds the environment and may take a few minutes.)
echo.

%PYEXE% RUN_BES.py

if errorlevel 1 (
    echo.
    echo [The app exited with an error - see messages above.]
    pause
)
