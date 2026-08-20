@echo off
cd /d "%~dp0"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    set PYCMD=py -3
) else (
    where python >nul 2>nul
    if %ERRORLEVEL%==0 (
        set PYCMD=python
    ) else (
        echo [ERROR] Python was not found on this PC.
        echo Install Python 3 from https://www.python.org/downloads/
        echo During setup, check the "Add python.exe to PATH" checkbox, then run this file again.
        pause
        exit /b 1
    )
)

echo Installing required packages, please wait...
%PYCMD% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install required packages ^(see the message above^).
    echo Check your internet connection and try again.
    pause
    exit /b 1
)

echo Starting Weather Duty...
%PYCMD% main.py

pause
