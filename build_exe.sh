#!/bin/bash
# macOS/Linux: Python 설치 없이 배포 가능한 단일 실행파일(WeatherDuty)을 만든다.
# 최초 1회만 실행하면 되고, 이후에는 dist/WeatherDuty 파일만 복사해서 사용하면 된다.
set -e
cd "$(dirname "$0")"

PYCMD=python3
echo "빌드 도구를 설치합니다..."
$PYCMD -m pip install --quiet -r requirements.txt pyinstaller

echo "WeatherDuty 를 빌드합니다..."
$PYCMD -m PyInstaller --onefile --windowed --name WeatherDuty main.py

echo
echo "완료되면 dist/WeatherDuty 파일이 생성됩니다."
echo "이 파일 하나만 복사하면 Python 설치 없이 다른 PC(같은 OS)에서도 실행할 수 있습니다."
