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

## 실행 방법

```bash
pip install -r requirements.txt
python -m weather_duty.app
```

Windows/Mac 표준 파이썬 설치본에는 tkinter가 기본 포함되어 있다. 일부 리눅스
배포판은 `sudo apt install python3-tk` 가 별도로 필요하다.

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
