@echo off
cd /d "%~dp0"
rem Builds a standalone WeatherDuty.exe that runs without Python installed.
rem Run this once; afterwards copy dist\WeatherDuty.exe to any Windows PC.

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    set PYCMD=py -3
) else (
    set PYCMD=python
)

echo Installing build tools, please wait...
%PYCMD% -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install required packages ^(see the message above^).
    pause
    exit /b 1
)

echo Building WeatherDuty.exe...
%PYCMD% -m PyInstaller --onefile --windowed --name WeatherDuty --add-data "weather_duty\data;weather_duty\data" main.py
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed ^(see the message above^).
    pause
    exit /b 1
)

echo.
echo Done. dist\WeatherDuty.exe was created.
echo Copy that single file to any Windows PC to run it without Python installed.
pause
