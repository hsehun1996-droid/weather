# weather-duty

폭염·풍수해·제설 근무를 위한 지역별 날씨 모니터. 서버 없이 로컬에서 실행하는
데스크톱 프로그램(파이썬 tkinter)으로, 기상청(공공데이터포털) API를 직접 호출한다.

## 기능

- 지역별 현재 기온 / 1시간 강수량 (초단기실황)
- 향후 예보: 단기예보(오늘~모레, 최저·최고기온/강수확률/강수량/하늘상태) +
  중기예보(3~10일 후, 최저·최고기온/강수확률/날씨)를 이어붙여 **가져올 수 있는
  최대 기간까지** 표시
- 기상특보 발효 현황 (당일 기준만 제공되며, 특보는 미래일에는 표시되지 않음 — 공란)
- 즐겨찾기 지역 관리: 상시 표출할 지역을 선택/편집, 좌표를 직접 입력해 지역 추가 가능

## 필요한 공공데이터포털 API (인증키 신청 필요)

아래 3개를 **모두** [data.go.kr](https://www.data.go.kr) 에서 "활용신청" 해야
하나의 서비스키로 전부 사용할 수 있다 (일반적으로 같은 계정 키가 승인 후
공통으로 적용됨).

1. **기상청_단기예보 ((구)동네예보) 조회서비스** (`VilageFcstInfoService_2.0`)
   - 초단기실황조회 `getUltraSrtNcst`, 단기예보조회 `getVilageFcst`
2. **기상청_중기예보 조회서비스** (`MidFcstInfoService`)
   - 중기기온조회 `getMidTa`, 중기육상예보조회 `getMidLandFcst`
3. **기상청_기상특보 조회서비스** (`WthrWrnInfoService02`)
   - 특보발표현황조회 `getWthrWrnList`

신청 후 승인되면 **일반 인증키(Decoding)** 값을 프로그램의 "설정(서비스키)"
화면에 입력하면 된다.

### 첨부 자료로 꼭 확인할 것

각 API 신청 페이지의 "활용가이드"에 아래 두 표가 첨부되어 있다. 이 프로그램의
`weather_duty/regions.py`에 들어있는 좌표는 예시값이라 반드시 이 표로 재검증
후 필요하면 수정/추가해야 한다.

- 단기예보용 **전국 격자좌표표** (읍면동 단위 nx, ny)
- 중기예보용 **중기예보구역코드표** (regId)

지역 관리 화면의 "+ 지역 직접 추가"로 이름/nx/ny/regId/특보 매칭 키워드를
입력하면 표에 없는 지역(시군구 단위)도 즐겨찾기에 추가할 수 있다.

### 기상특보 관련 한계

`getWthrWrnList`는 지역코드가 아니라 자유 텍스트(제목/내용)로 발효 중인 특보를
내려준다. 이 프로그램은 지역명이 그 텍스트에 포함되는지로 매칭한다(단순 키워드
매칭). 더 정교하게 하려면 기상청이 제공하는 특보구역코드표를 이용해 구조화된
매칭으로 바꿀 수 있다 — 필요하면 알려주면 추가로 구현 가능.

## 실행 방법 (뭘 누르면 되나요?)

**사전 준비 (최초 1회만):** [python.org](https://www.python.org/downloads/)에서
Python 3를 설치한다. Windows 설치 화면에서 **"Add python.exe to PATH"** 체크박스를
반드시 체크한다. tkinter는 표준 설치본에 기본 포함되어 있어 따로 설치할 필요가 없다.

그 다음부터는 아래 파일을 **더블클릭**하면 된다.

| OS | 더블클릭할 파일 |
| --- | --- |
| Windows | `run.bat` |
| macOS | `run.command` (최초 실행 시 "확인 없이 열기" 허용 필요할 수 있음) |

실행하면 검은 콘솔 창이 잠깐 뜨면서 필요한 라이브러리를 자동 설치한 뒤
프로그램 창이 뜬다. 처음 실행 시에는 프로그램 안의 **"설정(서비스키)"** 버튼을
눌러 공공데이터포털에서 받은 서비스키를 입력해야 데이터가 표시된다.

### Python 설치 없이 배포하고 싶다면 (완전한 .exe로 묶기)

담당자 PC마다 Python을 설치하기 번거롭다면, 아래 스크립트를 **한 번만** 실행해
Python 없이도 바로 실행되는 단일 실행파일을 만들 수 있다. 이 스크립트 자체는
Python이 설치된 PC에서 실행해야 하지만, 결과물(`WeatherDuty.exe`)은 다른
Windows PC에 Python 없이 그대로 복사해서 쓸 수 있다.

| OS | 더블클릭할 파일 | 결과물 |
| --- | --- | --- |
| Windows | `build_exe.bat` | `dist\WeatherDuty.exe` |
| macOS/Linux | `build_exe.sh` | `dist/WeatherDuty` |

> PyInstaller는 빌드한 OS용 실행파일만 만든다 (예: Mac에서 빌드하면 Mac용만
> 생성됨). Windows 배포용 exe가 필요하면 반드시 Windows PC에서 빌드해야 한다.

### 터미널에 익숙하다면

```bash
pip install -r requirements.txt
python main.py
```

## 설정 파일 위치

서비스키와 즐겨찾기 목록은 홈 디렉터리 아래에 저장되며(`~/.weather_duty/config.json`,
`~/.weather_duty/custom_regions.json`) 리포지토리에는 포함되지 않는다.

## 테스트

API 파싱 로직에 대한 단위 테스트(모킹, 네트워크 불필요):

```bash
python -m unittest discover -s weather_duty/tests -v
```

## 배포용 실행파일로 묶기 (선택)

개별 프로그램(exe/앱)으로 배포하려면 PyInstaller를 사용할 수 있다:

```bash
pip install pyinstaller
pyinstaller --onefile --windowed -n WeatherDuty weather_duty/app.py
```
