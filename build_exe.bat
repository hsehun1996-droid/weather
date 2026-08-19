@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem 파이썬 설치 없이도 배포할 수 있는 단일 실행파일(WeatherDuty.exe)을 만든다.
rem 최초 1회만 이 스크립트를 실행하면 되고, 이후에는 dist\WeatherDuty.exe 만
rem 복사해서 다른 PC에서도 그대로 실행할 수 있다.

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    set PYCMD=py -3
) else (
    set PYCMD=python
)

echo 빌드 도구를 설치합니다...
%PYCMD% -m pip install --quiet -r requirements.txt pyinstaller

echo WeatherDuty.exe 를 빌드합니다...
%PYCMD% -m PyInstaller --onefile --windowed --name WeatherDuty main.py

echo.
echo 완료되면 dist\WeatherDuty.exe 파일이 생성됩니다.
echo 이 파일 하나만 복사하면 Python 설치 없이 다른 PC에서도 실행할 수 있습니다.
pause
