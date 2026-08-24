@echo off
setlocal
title BES Bore-Log to DXF - Quick Convert
cd /d "%~dp0"

rem ------------------------------------------------------------------
rem  Drag and drop one or more .xls / .xlsx / .pdf files onto this
rem  file (or a shortcut to it) to convert them straight to DXF,
rem  no GUI needed. Output DXFs are written next to each input file.
rem
rem  Run Run_BoreLog_Tool.bat at least once first, so the required
rem  Python packages are installed.
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
        echo Please run Run_BoreLog_Tool.bat first.
        echo.
        pause
        exit /b 1
    )
)

rem --- verify required packages are installed -------------------------
%PY_CMD% -c "import ezdxf, xlrd, openpyxl, pdfplumber" >nul 2>nul
if errorlevel 1 (
    echo.
    echo [ERROR] Required Python packages are not installed.
    echo Please run Run_BoreLog_Tool.bat first to set up the environment.
    echo.
    pause
    exit /b 1
)

if "%~1"=="" (
    echo.
    echo Drag and drop one or more .xls / .xlsx / .pdf bore-log files
    echo onto this .bat file to convert them to DXF.
    echo.
    pause
    exit /b 0
)

echo Converting %* ...
echo.
%PY_CMD% -m borelog_dxf.cli %*

echo.
echo Done. DXF file(s) were saved next to the original file(s).
pause
endlocal
