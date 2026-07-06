@echo off
echo.
echo  Bridge Engineering Suite v2.0
echo  ================================
echo.

python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo  ERROR: Python not found. Install Python 3.10+ from https://python.org
    pause & exit /b 1
)

IF NOT EXIST "venv" (
    echo  Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo  Installing dependencies...
pip install -r requirements.txt --quiet --upgrade

echo.
echo  Launching Bridge Engineering Suite...
echo.
python main.py

pause
