@echo off
setlocal enabledelayedexpansion
title BES Bore-Log to DXF
cd /d "%~dp0"

rem ------------------------------------------------------------------
rem  BES Bore-Log to DXF - launcher
rem  First run: installs required packages into the user's Python.
rem  Every run after that: just opens the GUI.
rem
rem  NOTE: This system's Python is a Windows Store install where
rem  venv creation fails (python.exe is an App Execution Alias stub).
rem  Packages are installed via "pip install --user" instead.
rem ------------------------------------------------------------------

set PY_CMD=

rem --- find a Python interpreter -------------------------------------
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    set PY_CMD=py -3
) else (
    where python >nul 2>nul
    if %ERRORLEVEL%==0 (
        set PY_CMD=python
    ) else (
        echo.
        echo [ERROR] Python was not found on this machine.
        echo Install Python 3.10+ from https://www.python.org/downloads/
        echo and make sure "Add python.exe to PATH" is checked during install.
        echo.
        pause
        exit /b 1
    )
)

rem --- check that required packages are available --------------------
%PY_CMD% -c "import ezdxf, xlrd, openpyxl, pdfplumber, PyQt6" >nul 2>nul
if errorlevel 1 (
    echo First-time setup: installing required Python packages ...
    echo This can take a few minutes the first time.
    echo.
    %PY_CMD% -m pip install --user -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo.
        echo [ERROR] Failed to install required packages. Check your internet
        echo connection and re-run this file.
        pause
        exit /b 1
    )
    echo Setup complete.
    echo.
)

rem --- warn (but don't block) if Tesseract isn't on PATH ---------------
where tesseract >nul 2>nul
if not %ERRORLEVEL%==0 (
    echo [NOTE] Tesseract OCR was not found on PATH. Excel and text-based
    echo PDF conversion will work fine; OCR of scanned PDFs will not.
    echo Install it from: https://github.com/UB-Mannheim/tesseract/wiki
    echo.
)

echo Starting BES Bore-Log to DXF...
%PY_CMD% -m borelog_dxf.gui

if errorlevel 1 (
    echo.
    echo [ERROR] The application closed with an error - see the message above.
    pause
)

endlocal
