"""배포용 실행 진입점 (PyInstaller/더블클릭 실행 스크립트에서 사용).

패키지 상대 임포트(weather_duty/app.py)는 `python -m weather_duty.app` 처럼
패키지로 실행할 때만 동작하고, PyInstaller로 묶거나 스크립트 파일로 바로
실행하면 깨지므로 최상위에 절대 임포트 진입점을 따로 둔다.
"""
from weather_duty.gui import main

if __name__ == "__main__":
    main()
