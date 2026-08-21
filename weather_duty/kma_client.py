"""기상청(공공데이터포털) API 클라이언트.

사용하는 오픈API 3종:
  1. 단기예보 ((구)동네예보) 조회서비스 - VilageFcstInfoService_2.0
     - getUltraSrtNcst : 초단기실황(현재 기온/강수)
     - getVilageFcst   : 단기예보(오늘~모레/글피, 최저·최고기온, 강수확률/강수량, 하늘상태)
  2. 중기예보 조회서비스 - MidFcstInfoService
     - getMidTa       : 중기기온(3~10일 후 최저/최고기온)
     - getMidLandFcst : 중기육상예보(3~10일 후 하늘상태 텍스트, 강수확률)
  3. 기상특보 조회서비스 - WthrWrnInfoService
     - getWthrWrnList : 현재 발효 중인 특보 목록(자유 텍스트, 당일 기준만 제공)

data.go.kr에서 활용신청이 승인되어야 서비스키(인코딩/디코딩 키)를 받을 수 있다.
신청 페이지에서 위 3개 서비스를 모두 "활용신청"해야 한다.
"""
import datetime
import math
import re
import urllib.parse

import requests

try:
    # 회사/기관 보안 프로그램(SSL 검사·프록시)이 자체 인증서로 HTTPS 트래픽을
    # 가로채는 환경이 흔하다. 그 인증서는 Windows 신뢰 저장소에는 이미 등록돼
    # 있어 크롬은 문제없이 통과하지만, requests/certifi는 자체 CA 목록만 신뢰해
    # "self-signed certificate in certificate chain" 오류가 난다. truststore는
    # OS 신뢰 저장소(크롬이 쓰는 것과 동일)를 그대로 쓰도록 ssl 모듈을 바꿔준다.
    import truststore

    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001
    pass

try:
    # 사내망이 PAC(자동 프록시 설정 스크립트)를 쓰는 경우, 일반 requests는 이를
    # 인식하지 못해 브라우저는 되는데 이 프로그램만 연결에 실패할 수 있다.
    # pypac은 Windows/macOS의 PAC 설정을 자동으로 찾아 적용한다(없으면 무해하게
    # 일반 연결로 동작).
    import pypac

    _SESSION = pypac.PACSession()
except Exception:  # noqa: BLE001
    _SESSION = requests.Session()

BASE_VILAGE = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0"
BASE_MID = "https://apis.data.go.kr/1360000/MidFcstInfoService"
BASE_WARN = "https://apis.data.go.kr/1360000/WthrWrnInfoService"

TIMEOUT_SEC = 10

SKY_TEXT = {"1": "맑음", "3": "구름많음", "4": "흐림"}
PTY_TEXT = {"0": "없음", "1": "비", "2": "비/눈", "3": "눈", "4": "소나기"}

_PCP_NUMBER_RE = re.compile(r"([\d.]+)")


def _sum_daily_pcp(pcp_values):
    """단기예보 PCP는 3시간 구간별 범주형 문자열("1.0mm", "1mm 미만", "30.0mm 이상",
    "강수없음")로 내려온다. 하루치를 00~24시 누적값 하나로 합산한다.
    "미만"/"이상" 구간은 표기된 숫자를 그대로 쓰므로 근사치이며, "30.0mm 이상"이
    하루 중 한 구간이라도 있었으면 실제 누적량이 더 클 수 있어 합계에 "+"를 붙인다."""
    total = 0.0
    open_ended = False
    has_data = False
    for raw in pcp_values:
        if not raw or raw in ("강수없음", "-"):
            continue
        has_data = True
        match = _PCP_NUMBER_RE.search(raw)
        if not match:
            continue
        total += float(match.group(1))
        if "이상" in raw:
            open_ended = True
    if not has_data:
        return "강수없음"
    if total == 0:
        return "강수없음"
    formatted = f"{total:g}mm"
    return formatted + "+" if open_ended else formatted


def _wet_bulb_c(ta, rh):
    """Stull(2011) 근사식으로 습구온도(℃) 계산. ta=기온(℃), rh=상대습도(%)."""
    return (
        ta * math.atan(0.151977 * math.sqrt(rh + 8.313659))
        + math.atan(ta + rh)
        - math.atan(rh - 1.676331)
        + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh)
        - 4.686035
    )


def _heat_index_c(ta, rh):
    """여름철(5~9월) 체감온도 - 기상청이 2022년부터 쓰는 열지수 공식."""
    tw = _wet_bulb_c(ta, rh)
    return -0.2442 + 0.55399 * tw + 0.45535 * ta - 0.0022 * tw ** 2 + 0.00278 * tw * ta + 3.0


def _wind_chill_c(ta, ws_ms):
    """겨울철(10~4월) 체감온도 - 기상청 풍속냉각 공식. ws_ms=풍속(m/s)."""
    v_kmh = ws_ms * 3.6
    return 13.12 + 0.6215 * ta - 11.37 * (v_kmh ** 0.16) + 0.3965 * (v_kmh ** 0.16) * ta


def feels_like_c(ta, rh, ws_ms, month):
    """체감온도(℃) 근사치. 기상청은 5~9월엔 열지수(기온+습도) 공식, 10~4월엔
    풍속냉각 공식을 쓴다. 필요한 입력값(습도 또는 풍속)이 없으면 None."""
    if ta is None:
        return None
    try:
        ta = float(ta)
        if month in (5, 6, 7, 8, 9):
            if rh is None:
                return None
            return _heat_index_c(ta, float(rh))
        if ws_ms is None:
            return None
        return _wind_chill_c(ta, float(ws_ms))
    except (TypeError, ValueError):
        return None


class KmaApiError(Exception):
    pass


def _service_key_param(service_key):
    """서비스키를 그대로 쓴다. data.go.kr 키는 이미 URL-encoded 형태로 발급되는
    경우가 많아, requests가 다시 인코딩하지 않도록 params 대신 쿼리스트링에
    직접 붙여서 호출한다."""
    return service_key


def _redact(text, service_key):
    """오류 메시지에 서비스키가 그대로 노출되지 않도록 마스킹한다.
    (오류 화면을 캡처해 공유해도 키가 유출되지 않게 하기 위함)"""
    if not service_key:
        return text
    text = text.replace(service_key, "***")
    quoted = urllib.parse.quote(service_key, safe="")
    if quoted != service_key:
        text = text.replace(quoted, "***")
    return text


def _get(url, service_key, params):
    query = {"serviceKey": _service_key_param(service_key), "dataType": "JSON"}
    query.update(params)
    # serviceKey는 이미 인코딩된 값일 수 있으므로 requests의 자동 인코딩과
    # 충돌하지 않도록 수동으로 쿼리스트링을 구성한다.
    encoded_key = query.pop("serviceKey")
    qs = urllib.parse.urlencode(query)
    full_url = f"{url}?serviceKey={encoded_key}&{qs}"
    try:
        resp = _SESSION.get(full_url, timeout=TIMEOUT_SEC)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        raise KmaApiError(
            f"[HTTP 오류 {exc.response.status_code}] {_redact(str(exc), service_key)}"
        ) from exc
    except requests.exceptions.SSLError as exc:
        raise KmaApiError(
            "[SSL 인증서 오류] 백신 프로그램이나 사내 보안 프로그램(SSL 검사/프록시)이 "
            f"연결을 가로채고 있을 수 있습니다. 상세: {_redact(str(exc), service_key)}"
        ) from exc
    except requests.exceptions.ConnectTimeout as exc:
        raise KmaApiError(
            "[연결 시간 초과] 기상청 서버에 연결하지 못했습니다. 사내망이라면 "
            "방화벽에서 apis.data.go.kr(443 포트) 아웃바운드를 막고 있을 수 있습니다. "
            f"상세: {_redact(str(exc), service_key)}"
        ) from exc
    except requests.exceptions.ConnectionError as exc:
        raise KmaApiError(
            "[연결 실패] 인터넷 연결 상태를 확인하거나, 사내망이라면 관리자에게 "
            f"apis.data.go.kr(443 포트) 아웃바운드 허용을 요청하세요. 상세: {_redact(str(exc), service_key)}"
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise KmaApiError(
            f"[응답 지연] 기상청 서버 응답이 너무 느립니다. 상세: {_redact(str(exc), service_key)}"
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise KmaApiError(f"[네트워크 오류] {_redact(str(exc), service_key)}") from exc
    try:
        data = resp.json()
    except ValueError:
        raise KmaApiError(
            f"JSON이 아닌 응답 (인증키 오류 가능): {_redact(resp.text[:200], service_key)}"
        )

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


def _base_datetime_for_today_full_day(now=None):
    """당일(오늘) 00~24시를 전부 포함하는 가장 이른 발표시각(전날 23시)을 반환.
    최신 발표(base_time)만 쓰면 발표시각 이전 구간(예: 오늘 00~14시)이 빠져,
    당일 누적강수량/체감온도/기온이 "지금부터 24시까지"만 반영된 값이 되는 문제가 있다."""
    now = now or datetime.datetime.now()
    yesterday = now.date() - datetime.timedelta(days=1)
    return yesterday.strftime("%Y%m%d"), "2300"


def _fetch_vilage_items(service_key, base_date, base_time, nx, ny):
    return _get(
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


def _group_vilage_items_by_date(items):
    by_date = {}
    for it in items:
        date = it["fcstDate"]
        time = it["fcstTime"]
        category = it["category"]
        value = it["fcstValue"]
        day = by_date.setdefault(date, {"date": date, "tmin": None, "tmax": None, "by_time": {}})
        slot = day["by_time"].setdefault(time, {"time": time})

        if category == "TMN":
            day["tmin"] = value
        elif category == "TMX":
            day["tmax"] = value
        elif category == "TMP":
            slot["temp"] = value
        elif category == "POP":
            slot["pop"] = int(value)
        elif category == "PCP":
            slot["pcp"] = value
        elif category == "REH":
            slot["reh"] = value
        elif category == "WSD":
            slot["wsd"] = value
        elif category == "SKY":
            slot["sky"] = value
        elif category == "PTY":
            slot["pty"] = value
    return by_date


def _build_day_entry(date, day_data):
    month = int(date[4:6])
    slots = [day_data["by_time"][t] for t in sorted(day_data["by_time"])]

    hourly = []
    feels_like_values = []
    for slot in slots:
        temp = slot.get("temp")
        reh = slot.get("reh")
        wsd = slot.get("wsd")
        feels_like = feels_like_c(temp, reh, wsd, month)
        if feels_like is not None:
            feels_like_values.append(feels_like)
        pty_val = slot.get("pty")
        sky_val = slot.get("sky")
        condition = (
            PTY_TEXT.get(pty_val, "") if pty_val and pty_val != "0" else SKY_TEXT.get(sky_val, "")
        )
        hourly.append(
            {
                "time": slot["time"],
                "temp": temp,
                "feels_like": feels_like,
                "pop": slot.get("pop"),
                "pcp": slot.get("pcp"),
                "condition": condition,
            }
        )

    pop_vals = [s["pop"] for s in slots if s.get("pop") is not None]
    pop_max = max(pop_vals) if pop_vals else None
    pty_vals = [s.get("pty") for s in slots if s.get("pty") is not None]
    sky_vals = [s.get("sky") for s in slots if s.get("sky") is not None]
    sky_val = sky_vals[len(sky_vals) // 2] if sky_vals else None
    pty_val = next((v for v in pty_vals if v != "0"), (pty_vals[0] if pty_vals else None))
    condition = PTY_TEXT.get(pty_val, "") if pty_val and pty_val != "0" else SKY_TEXT.get(sky_val, "")

    return {
        "date": date,
        "tmin": day_data["tmin"],
        "tmax": day_data["tmax"],
        "pop": pop_max,
        "pcp": _sum_daily_pcp([s.get("pcp") for s in slots if s.get("pcp") is not None]),
        "condition": condition,
        "source": "단기예보",
        "feels_like_min": round(min(feels_like_values), 1) if feels_like_values else None,
        "feels_like_max": round(max(feels_like_values), 1) if feels_like_values else None,
        "hourly": hourly,
    }


def get_short_term_forecast(service_key, nx, ny, now=None):
    """단기예보: 오늘부터 최대 모레/글피까지 일자별 최저/최고기온, 강수확률,
    강수량, 하늘상태를 날짜별로 묶어서 반환.

    당일(오늘) 항목은 최신 발표 대신, 오늘 00시를 포함하는 가장 이른 발표(전날 23시)를
    별도로 조회해 00~24시 전체 기준으로 교체한다. (다른 날짜는 최신 발표 그대로 사용)"""
    now = now or datetime.datetime.now()
    base_date, base_time = _base_datetime_for_vilage(now)
    items = _fetch_vilage_items(service_key, base_date, base_time, nx, ny)
    by_date = _group_vilage_items_by_date(items)
    result = [_build_day_entry(date, by_date[date]) for date in sorted(by_date)]

    today = now.strftime("%Y%m%d")
    anchor_date, anchor_time = _base_datetime_for_today_full_day(now)
    if today in by_date and (base_date, base_time) != (anchor_date, anchor_time):
        try:
            anchor_items = _fetch_vilage_items(service_key, anchor_date, anchor_time, nx, ny)
            anchor_by_date = _group_vilage_items_by_date(anchor_items)
            if today in anchor_by_date:
                today_entry = _build_day_entry(today, anchor_by_date[today])
                result = [today_entry if d["date"] == today else d for d in result]
        except KmaApiError:
            pass  # 조회 실패 시 최신 발표 기준(부분 구간) 값을 그대로 둔다

    return result


def sum_pcp_range(pcp_values):
    """주어진 3시간 구간별 강수량 문자열들을 하나의 누적값 문구로 합산.
    (지사별 시간대 선택 누적강수량 비교에서 사용)"""
    return _sum_daily_pcp(pcp_values)


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
                "feels_like_min": None,
                "feels_like_max": None,
                "hourly": [],
            }
        )
    return result


_WARN_TEXT_FIELDS = ("t1", "t2", "t3", "t4", "t6", "t7", "other", "warFc")


def get_active_warnings(service_key, now=None):
    """현재 발효 중인 기상특보 목록(통보문 텍스트)을 반환.
    getWthrWrnMsg는 stnId(관측지점번호)가 필수이며, 특보구역별로 나뉘지 않고
    지역명이 포함된 자유 텍스트(t1~t7 등)로 내려오므로, 지역별 매칭은 호출부에서
    키워드 포함 여부로 판단한다. stnId=108(서울)은 전국 특보를 포괄해서 보여주는
    대표 지점으로 흔히 쓰인다."""
    now = now or datetime.datetime.now()
    today = now.strftime("%Y%m%d")
    items = _get(
        f"{BASE_WARN}/getWthrWrnMsg",
        service_key,
        {"numOfRows": 100, "pageNo": 1, "stnId": 108, "fromTmFc": today, "toTmFc": today},
    )
    warnings = []
    for it in items:
        text = " ".join(str(it.get(k, "")) for k in _WARN_TEXT_FIELDS if it.get(k))
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
    mid_land_regid = region_info.get("mid_land_regid")
    mid_ta_regid = region_info.get("mid_ta_regid")
    if mid_land_regid and mid_ta_regid:
        try:
            mid_term = get_mid_term_forecast(service_key, mid_land_regid, mid_ta_regid, now)
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
