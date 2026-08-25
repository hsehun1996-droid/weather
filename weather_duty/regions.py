"""지역 코드 프리셋(전국 250개 시군구)과 사용자 정의 지역 관리.

기상청 API는 서비스마다 서로 다른 지역 좌표계를 쓴다.
  - 단기예보/초단기실황(getVilageFcst, getUltraSrtNcst): 격자 좌표 nx, ny
    -> 시군구 중심 위경도를 기상청 LCC 격자변환 공식(grid.py)으로 직접 계산.
  - 중기기온(getMidTa): 도시 단위 지역코드(mid_ta_regid). 전국 193개 지점의
    위경도-코드 대응표(data/midterm_ta_points.csv)에서 가장 가까운 지점의
    코드를 사용한다. 이 표는 공개된 기상청 활용 예제 프로젝트에 포함된
    city_latlon.xlsx를 그대로 옮긴 것.
  - 중기육상예보(getMidLandFcst): 훨씬 넓은 10개 권역 단위 코드(mid_land_regid).
    (수도권/강원영서/강원영동/충북/대전세종충남/전북/광주전남/대구경북/
    부산울산경남/제주) 시도명(강원은 영동·영서 구분)으로 결정한다.
  - 기상특보(getWthrWrnMsg): 구조화된 지역코드가 아니라 자유 텍스트(제목/내용)로
    내려오므로, 텍스트에 지역명이 포함되는지로 매칭한다 (warn_keyword).
  - 지상(종관, ASOS) 시간자료(getWthrDataList, 과거 실측): 관측지점번호(stnId).
    전국 97개 현재 운영 중인 관측소의 위경도(data/asos_stations.csv, 기상자료개방포털에서
    받은 관측지점정보 메타데이터 기준)에서 가장 가까운 지점을 쓴다.

시군구 중심 좌표만으로는 같은 시군구 안의 특정 읍/면/동까지는 못 짚는다.
그런 세밀한 위치가 필요하면 "지역 관리"에서 위도/경도를 직접 입력해
사용자 정의 지역으로 추가하면 된다(add_custom_region).
"""
import csv
import json
import os

from . import grid

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
_SIGUNGU_CSV = os.path.join(_DATA_DIR, "sigungu.csv")
_MIDTERM_TA_CSV = os.path.join(_DATA_DIR, "midterm_ta_points.csv")
_ASOS_STATIONS_CSV = os.path.join(_DATA_DIR, "asos_stations.csv")

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".weather_duty")
CUSTOM_REGIONS_PATH = os.path.join(CONFIG_DIR, "custom_regions.json")

GANGWON_YEONGDONG = {"강릉시", "동해시", "속초시", "삼척시", "고성군", "양양군"}

SIDO_NAMES = [
    "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시",
    "대전광역시", "울산광역시", "세종특별자치시", "경기도", "강원특별자치도",
    "충청북도", "충청남도", "전북특별자치도", "전라남도", "경상북도",
    "경상남도", "제주특별자치도",
]


def _mid_land_regid(sido_name, sigungu_name):
    if sido_name in ("서울특별시", "인천광역시", "경기도"):
        return "11B00000"
    if sido_name.startswith("강원"):
        return "11D20000" if sigungu_name in GANGWON_YEONGDONG else "11D10000"
    if sido_name == "충청북도":
        return "11C10000"
    if sido_name in ("대전광역시", "세종특별자치시", "충청남도"):
        return "11C20000"
    if sido_name.startswith("전북") or sido_name == "전라북도":
        return "11F10000"
    if sido_name in ("광주광역시", "전라남도"):
        return "11F20000"
    if sido_name in ("대구광역시", "경상북도"):
        return "11H10000"
    if sido_name in ("부산광역시", "울산광역시", "경상남도"):
        return "11H20000"
    if sido_name.startswith("제주"):
        return "11G00000"
    return "11B00000"


def _load_midterm_ta_points():
    points = []
    with open(_MIDTERM_TA_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            points.append(
                {"lat": float(row["lat"]), "lon": float(row["lon"]), "reg_id": row["reg_id"]}
            )
    return points


def _nearest_mid_ta_regid(lat, lon, points):
    best = min(points, key=lambda p: (p["lat"] - lat) ** 2 + (p["lon"] - lon) ** 2)
    return best["reg_id"]


def _load_asos_stations():
    stations = []
    with open(_ASOS_STATIONS_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            stations.append(
                {"stn_id": row["stn_id"], "name": row["name"], "lat": float(row["lat"]), "lon": float(row["lon"])}
            )
    return stations


def _nearest_asos_stn_id(lat, lon, stations):
    best = min(stations, key=lambda s: (s["lat"] - lat) ** 2 + (s["lon"] - lon) ** 2)
    return best["stn_id"]


def build_region_info(lat, lon, sido_name, sigungu_name, midterm_points, asos_stations=None):
    nx, ny = grid.latlon_to_grid(lat, lon)
    if asos_stations is None:
        asos_stations = _load_asos_stations()
    return {
        "nx": nx,
        "ny": ny,
        "lat": lat,
        "lon": lon,
        "mid_ta_regid": _nearest_mid_ta_regid(lat, lon, midterm_points),
        "mid_land_regid": _mid_land_regid(sido_name, sigungu_name),
        "warn_keyword": sigungu_name,
        "asos_stn_id": _nearest_asos_stn_id(lat, lon, asos_stations),
    }


_preset_cache = None


def _load_preset_regions():
    global _preset_cache
    if _preset_cache is not None:
        return _preset_cache

    midterm_points = _load_midterm_ta_points()
    asos_stations = _load_asos_stations()
    presets = {}
    with open(_SIGUNGU_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = f"{row['sido_name']} {row['sigungu_name']}"
            lat, lon = float(row["lat"]), float(row["lon"])
            presets[name] = build_region_info(
                lat, lon, row["sido_name"], row["sigungu_name"], midterm_points, asos_stations
            )
    _preset_cache = presets
    return presets


def _ensure_config_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)


def load_custom_regions():
    _ensure_config_dir()
    if not os.path.exists(CUSTOM_REGIONS_PATH):
        return {}
    with open(CUSTOM_REGIONS_PATH, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_custom_regions(custom_regions):
    _ensure_config_dir()
    with open(CUSTOM_REGIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(custom_regions, f, ensure_ascii=False, indent=2)


def all_regions():
    """전국 시군구 프리셋(250개) + 사용자 정의 지역을 합쳐서 반환."""
    regions = dict(_load_preset_regions())
    regions.update(load_custom_regions())
    return regions


def add_custom_region(name, lat, lon, sido_name, sigungu_name=None, warn_keyword=None):
    """위도/경도만 알면 되는 사용자 정의 지역 추가(예: 특정 읍/면/동).

    sido_name은 중기육상예보 권역(강원 영동/영서 등) 판별에 쓰인다.
    """
    midterm_points = _load_midterm_ta_points()
    info = build_region_info(
        float(lat), float(lon), sido_name, sigungu_name or name, midterm_points
    )
    if warn_keyword:
        info["warn_keyword"] = warn_keyword
    custom = load_custom_regions()
    custom[name] = info
    save_custom_regions(custom)


def remove_custom_region(name):
    custom = load_custom_regions()
    if name in custom:
        del custom[name]
        save_custom_regions(custom)
