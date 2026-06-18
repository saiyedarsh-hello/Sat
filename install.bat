@echo off
setlocal

echo ========================================================
echo Saturday AI Desktop Assistant - Installer
echo ========================================================
echo.

set "PYTHON_CMD="

where py >nul 2>nul
if %errorlevel%==0 set "PYTHON_CMD=py -3"

if not defined PYTHON_CMD (
    where python >nul 2>nul
    if %errorlevel%==0 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo Python was not found.
    echo.
    echo Please install Python 3.11 or newer from:
    echo   https://www.python.org/downloads/windows/
    echo.
    echo IMPORTANT:
    echo   On the first installer screen, tick:
    echo   [x] Add python.exe to PATH
    echo.
    echo After installing Python, close this terminal, open a new PowerShell window,
    echo then run:
    echo   cd C:\Users\saiye\Documents\Saturday
    echo   .\install.bat
    echo.
    start "" "https://www.python.org/downloads/windows/"
    pause
    exit /b 1
)

echo Using Python:
%PYTHON_CMD% --version
echo.

echo Installing Python dependencies...
%PYTHON_CMD% -m pip install --upgrade pip
%PYTHON_CMD% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Dependency installation failed.
    pause
    exit /b 1
)

echo.
echo Setup complete.
echo Start Saturday with:
echo   %PYTHON_CMD% main.py
echo.
echo To build the app:
echo   %PYTHON_CMD% -m pip install pyinstaller
echo   %PYTHON_CMD% -m PyInstaller saturday.spec
echo.
pause
