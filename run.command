#!/bin/bash
# macOS: 이 파일을 더블클릭하면 실행됩니다 (최초 1회 "확인 없이 열기" 허용 필요할 수 있음).
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
    PYCMD=python3
else
    echo "Python3가 설치되어 있지 않습니다."
    echo "https://www.python.org/downloads/ 에서 Python 3 를 설치한 뒤 다시 실행하세요."
    read -p "엔터를 누르면 종료합니다..." _
    exit 1
fi

echo "필요한 라이브러리를 설치합니다..."
$PYCMD -m pip install --quiet -r requirements.txt

echo "프로그램을 실행합니다..."
$PYCMD main.py
