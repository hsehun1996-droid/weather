"""기상청(공공데이터포털) API 클라이언트.

사용하는 오픈API 3종:
  1. 단기예보 ((구)동네예보) 조회서비스 - VilageFcstInfoService_2.0
     - getUltraSrtNcst : 초단기실황(현재 기온/강수)
     - getVilageFcst   : 단기예보(오늘~모레/글피, 최저·최고기온, 강수확률/강수량, 하늘상태)
  2. 중기예보 조회서비스 - MidFcstInfoService
     - getMidTa       : 중기기온(3~10일 후 최저/최고기온)
     - getMidLandFcst : 중기육상예보(3~10일 후 하늘상태 텍스트, 강수확률)
  3. 기상특보 조회서비스 - WthrWrnInfoService02
     - getWthrWrnList : 현재 발효 중인 특보 목록(자유 텍스트, 당일 기준만 제공)

data.go.kr에서 활용신청이 승인되어야 서비스키(인코딩/디코딩 키)를 받을 수 있다.
신청 페이지에서 위 3개 서비스를 모두 "활용신청"해야 한다.
"""
import datetime
import urllib.parse

import requests

BASE_VILAGE = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0"
BASE_MID = "https://apis.data.go.kr/1360000/MidFcstInfoService"
BASE_WARN = "https://apis.data.go.kr/1360000/WthrWrnInfoService02"

TIMEOUT_SEC = 10

SKY_TEXT = {"1": "맑음", "3": "구름많음", "4": "흐림"}
PTY_TEXT = {"0": "없음", "1": "비", "2": "비/눈", "3": "눈", "4": "소나기"}


class KmaApiError(Exception):
    pass


def _service_key_param(service_key):
    """서비스키를 그대로 쓴다. data.go.kr 키는 이미 URL-encoded 형태로 발급되는
    경우가 많아, requests가 다시 인코딩하지 않도록 params 대신 쿼리스트링에
    직접 붙여서 호출한다."""
    return service_key


def _get(url, service_key, params):
    query = {"serviceKey": _service_key_param(service_key), "dataType": "JSON"}
    query.update(params)
    # serviceKey는 이미 인코딩된 값일 수 있으므로 requests의 자동 인코딩과
    # 충돌하지 않도록 수동으로 쿼리스트링을 구성한다.
    encoded_key = query.pop("serviceKey")
    qs = urllib.parse.urlencode(query)
    full_url = f"{url}?serviceKey={encoded_key}&{qs}"
    resp = requests.get(full_url, timeout=TIMEOUT_SEC)
    resp.raise_for_status()
    try:
        data = resp.json()
    except ValueError:
        raise KmaApiError(f"JSON이 아닌 응답 (인증키 오류 가능): {resp.text[:200]}")

    header = data.get("response", {}).get("header", {})
    if header.get("resultCode") not in ("00", "0"):
        raise KmaApiError(f"{header.get('resultCode')}: {header.get('resultMsg')}")

    body = data.get("response", {}).get("body", {})
    items = body.get("items", {})
    if items == "" or items is None:
        return []
    item = items.get("item", [])
    if isinstance(item, dict):
        item = [item]
    return item


def _base_datetime_for_ncst(now=None):
    """초단기실황은 매 정시 10분 이후 생성, 40분 이전 조회 시 직전 시각 사용."""
    now = now or datetime.datetime.now()
    if now.minute < 40:
        now = now - datetime.timedelta(hours=1)
    return now.strftime("%Y%m%d"), now.strftime("%H00")


def _base_datetime_for_vilage(now=None):
    """단기예보 base_time은 02,05,08,11,14,17,20,23시 발표. 발표 후 10분 뒤 제공."""
    now = now or datetime.datetime.now()
    base_hours = [2, 5, 8, 11, 14, 17, 20, 23]
    candidate = now - datetime.timedelta(minutes=10)
    hour = candidate.hour
    chosen = max([h for h in base_hours if h <= hour], default=None)
    base_date = candidate.date()
    if chosen is None:
        chosen = 23
        base_date = base_date - datetime.timedelta(days=1)
    return base_date.strftime("%Y%m%d"), f"{chosen:02d}00"


def get_current_conditions(service_key, nx, ny, now=None):
    """현재 기온(T1H, ℃)과 1시간 강수량(RN1)을 반환."""
    base_date, base_time = _base_datetime_for_ncst(now)
    items = _get(
        f"{BASE_VILAGE}/getUltraSrtNcst",
        service_key,
        {
            "numOfRows": 20,
            "pageNo": 1,
            "base_date": base_date,
            "base_time": base_time,
            "nx": nx,
            "ny": ny,
        },
    )
    values = {it["category"]: it["obsrValue"] for it in items}
    return {
        "temp": values.get("T1H"),
        "rain_1h": values.get("RN1"),
        "obs_time": f"{base_date} {base_time}",
    }


def get_short_term_forecast(service_key, nx, ny, now=None):
    """단기예보: 오늘부터 최대 모레/글피까지 일자별 최저/최고기온, 강수확률,
    강수량, 하늘상태를 날짜별로 묶어서 반환."""
    base_date, base_time = _base_datetime_for_vilage(now)
    items = _get(
        f"{BASE_VILAGE}/getVilageFcst",
        service_key,
        {
            "numOfRows": 1000,
            "pageNo": 1,
            "base_date": base_date,
            "base_time": base_time,
            "nx": nx,
            "ny": ny,
        },
    )

    by_date = {}
    for it in items:
        date = it["fcstDate"]
        time = it["fcstTime"]
        category = it["category"]
        value = it["fcstValue"]
        day = by_date.setdefault(
            date,
            {"date": date, "tmin": None, "tmax": None, "pop": [], "pcp": [], "sky": [], "pty": []},
        )
        if category == "TMN":
            day["tmin"] = value
        elif category == "TMX":
            day["tmax"] = value
        elif category == "TMP" and time in ("0600", "1500"):
            # TMN/TMX가 안 나오는 날짜(오늘) 보정용 참고 기온
            day.setdefault("tmp_ref", {})[time] = value
        elif category == "POP":
            day["pop"].append(int(value))
        elif category == "PCP":
            day["pcp"].append(value)
        elif category == "SKY":
            day["sky"].append(value)
        elif category == "PTY":
            day["pty"].append(value)

    result = []
    for date in sorted(by_date):
        d = by_date[date]
        pop_max = max(d["pop"]) if d["pop"] else None
        pcp_vals = [v for v in d["pcp"] if v and v != "강수없음"]
        sky_val = d["sky"][len(d["sky"]) // 2] if d["sky"] else None
        pty_val = next((v for v in d["pty"] if v != "0"), (d["pty"][0] if d["pty"] else None))
        condition = PTY_TEXT.get(pty_val, "") if pty_val and pty_val != "0" else SKY_TEXT.get(sky_val, "")
        result.append(
            {
                "date": date,
                "tmin": d["tmin"],
                "tmax": d["tmax"],
                "pop": pop_max,
                "pcp": ", ".join(pcp_vals) if pcp_vals else "강수없음",
                "condition": condition,
                "source": "단기예보",
            }
        )
    return result


def get_mid_term_forecast(service_key, reg_id_land, reg_id_ta, now=None):
    """중기예보: 3~10일 후 최저/최고기온과 하늘상태(강수확률)를 날짜별로 반환.
    reg_id_land: 중기육상예보구역코드, reg_id_ta: 중기기온구역코드(대개 동일)."""
    now = now or datetime.datetime.now()
    # 중기예보는 06시, 18시 하루 2회 발표. 발표 이후 시각으로 tmFc 구성.
    if now.hour >= 18:
        tm_fc = now.strftime("%Y%m%d") + "1800"
    elif now.hour >= 6:
        tm_fc = now.strftime("%Y%m%d") + "0600"
    else:
        yesterday = now - datetime.timedelta(days=1)
        tm_fc = yesterday.strftime("%Y%m%d") + "1800"

    ta_items = _get(
        f"{BASE_MID}/getMidTa",
        service_key,
        {"numOfRows": 10, "pageNo": 1, "regId": reg_id_ta, "tmFc": tm_fc},
    )
    land_items = _get(
        f"{BASE_MID}/getMidLandFcst",
        service_key,
        {"numOfRows": 10, "pageNo": 1, "regId": reg_id_land, "tmFc": tm_fc},
    )

    ta = ta_items[0] if ta_items else {}
    land = land_items[0] if land_items else {}

    base_date = datetime.datetime.strptime(tm_fc[:8], "%Y%m%d").date()
    result = []
    for day_no in range(3, 11):
        date = (base_date + datetime.timedelta(days=day_no)).strftime("%Y%m%d")
        tmin = ta.get(f"taMin{day_no}")
        tmax = ta.get(f"taMax{day_no}")
        if day_no <= 7:
            condition_am = land.get(f"wf{day_no}Am")
            condition_pm = land.get(f"wf{day_no}Pm")
            pop_am = land.get(f"rnSt{day_no}Am")
            pop_pm = land.get(f"rnSt{day_no}Pm")
            condition = condition_am or condition_pm or ""
            if condition_am and condition_pm and condition_am != condition_pm:
                condition = f"오전 {condition_am} / 오후 {condition_pm}"
            pop = max([p for p in (pop_am, pop_pm) if p is not None], default=None)
        else:
            condition = land.get(f"wf{day_no}", "")
            pop = land.get(f"rnSt{day_no}")

        if tmin is None and tmax is None and not condition:
            continue
        result.append(
            {
                "date": date,
                "tmin": tmin,
                "tmax": tmax,
                "pop": pop,
                "pcp": "",
                "condition": condition,
                "source": "중기예보",
            }
        )
    return result


def get_active_warnings(service_key, now=None):
    """현재 발효 중인 기상특보 목록(제목/내용 텍스트)을 반환.
    이 API는 지역코드가 아닌 자유 텍스트로 내려오므로, 지역별 매칭은
    호출부에서 키워드 포함 여부로 판단한다."""
    now = now or datetime.datetime.now()
    items = _get(
        f"{BASE_WARN}/getWthrWrnList",
        service_key,
        {"numOfRows": 100, "pageNo": 1, "fromTmFc": (now - datetime.timedelta(days=1)).strftime("%Y%m%d0000"), "toTmFc": now.strftime("%Y%m%d%H%M")},
    )
    warnings = []
    for it in items:
        text = " ".join(str(it.get(k, "")) for k in ("title", "t6", "t3") if it.get(k))
        warnings.append({"raw": it, "text": text})
    return warnings


def match_region_warning(warnings, warn_keyword):
    matched = [w["text"] for w in warnings if warn_keyword and warn_keyword in w["text"]]
    return matched


def build_region_report(service_key, region_name, region_info, warnings, now=None):
    """지역 하나에 대한 통합 리포트: 현재 상태 + 향후 예보(최대 10일) + 특보(당일만)."""
    report = {"name": region_name, "current": None, "forecast": [], "warnings": [], "errors": []}

    try:
        report["current"] = get_current_conditions(service_key, region_info["nx"], region_info["ny"], now)
    except Exception as exc:  # noqa: BLE001 - 개별 지역 오류가 전체를 막지 않도록
        report["errors"].append(f"실황 조회 실패: {exc}")

    short_term = []
    try:
        short_term = get_short_term_forecast(service_key, region_info["nx"], region_info["ny"], now)
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"단기예보 조회 실패: {exc}")

    mid_term = []
    reg_id = region_info.get("regId")
    if reg_id:
        try:
            mid_term = get_mid_term_forecast(service_key, reg_id, reg_id, now)
        except Exception as exc:  # noqa: BLE001
            report["errors"].append(f"중기예보 조회 실패: {exc}")

    short_dates = {d["date"] for d in short_term}
    combined = list(short_term) + [d for d in mid_term if d["date"] not in short_dates]
    combined.sort(key=lambda d: d["date"])
    report["forecast"] = combined

    try:
        report["warnings"] = match_region_warning(warnings, region_info.get("warn_keyword", region_name))
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"특보 매칭 실패: {exc}")

    return report
