"""지역 코드 프리셋과 사용자 정의 지역 관리.

기상청 API는 서비스마다 서로 다른 지역 좌표계를 쓴다.
  - 단기예보/초단기실황(getVilageFcst, getUltraSrtNcst): 격자 좌표 nx, ny
  - 중기예보(getMidTa, getMidLandFcst): 중기예보구역코드 regId
  - 기상특보(getWthrWrnList): 구조화된 지역코드가 아니라 자유 텍스트(제목/내용)로
    내려오므로, 텍스트에 지역명이 포함되는지로 매칭한다 (warn_keyword).

아래 PRESET_REGIONS 의 좌표는 자주 인용되는 값이지만, 실제 근무에 쓰기 전에
공공데이터포털에서 API 신청 시 받는 활용가이드 첨부파일(전국 격자좌표표,
중기예보구역코드표)로 반드시 재검증할 것. 다른 지역은 "지역 관리" 화면에서
nx/ny, regId, 특보 매칭 키워드를 직접 입력해 추가하면 된다.
"""
import json
import os

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".weather_duty")
CUSTOM_REGIONS_PATH = os.path.join(CONFIG_DIR, "custom_regions.json")

# name -> {nx, ny, regId, warn_keyword}
PRESET_REGIONS = {
    "서울": {"nx": 60, "ny": 127, "regId": "11B10101", "warn_keyword": "서울"},
    "인천": {"nx": 55, "ny": 124, "regId": "11B20201", "warn_keyword": "인천"},
    "대전": {"nx": 67, "ny": 100, "regId": "11C20401", "warn_keyword": "대전"},
    "대구": {"nx": 89, "ny": 90, "regId": "11H10701", "warn_keyword": "대구"},
    "광주": {"nx": 58, "ny": 74, "regId": "11F20501", "warn_keyword": "광주"},
    "부산": {"nx": 98, "ny": 76, "regId": "11H20201", "warn_keyword": "부산"},
    "울산": {"nx": 102, "ny": 84, "regId": "11H20101", "warn_keyword": "울산"},
    "세종": {"nx": 66, "ny": 103, "regId": "11C20404", "warn_keyword": "세종"},
    "제주": {"nx": 52, "ny": 38, "regId": "11G00201", "warn_keyword": "제주"},
}

_NOTE = (
    "좌표는 예시값입니다. data.go.kr에서 API 신청 후 제공되는 "
    "'격자좌표표'와 '중기예보구역코드표'로 반드시 확인/보정하세요."
)


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
    """프리셋 + 사용자 정의 지역을 합쳐서 반환."""
    regions = dict(PRESET_REGIONS)
    regions.update(load_custom_regions())
    return regions


def add_custom_region(name, nx, ny, reg_id, warn_keyword=None):
    custom = load_custom_regions()
    custom[name] = {
        "nx": int(nx),
        "ny": int(ny),
        "regId": reg_id,
        "warn_keyword": warn_keyword or name,
    }
    save_custom_regions(custom)


def remove_custom_region(name):
    custom = load_custom_regions()
    if name in custom:
        del custom[name]
        save_custom_regions(custom)
