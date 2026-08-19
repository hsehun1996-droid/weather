@echo off
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    set PYCMD=py -3
) else (
    where python >nul 2>nul
    if %ERRORLEVEL%==0 (
        set PYCMD=python
    ) else (
        echo Python이 설치되어 있지 않습니다.
        echo https://www.python.org/downloads/ 에서 Python 3 를 내려받아 설치한 뒤,
        echo 설치 화면에서 "Add python.exe to PATH" 체크박스를 반드시 체크하세요.
        pause
        exit /b 1
    )
)

echo 필요한 라이브러리를 설치합니다...
%PYCMD% -m pip install --quiet -r requirements.txt

echo 프로그램을 실행합니다...
%PYCMD% main.py

pause
