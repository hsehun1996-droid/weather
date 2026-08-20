"""사용자 설정(서비스키, 즐겨찾기 목록) 저장/로드.

설정은 홈 디렉터리 아래 ~/.weather_duty/config.json 에 저장한다.
서비스 키가 담기므로 이 파일은 절대 git에 커밋하지 않는다.
"""
import json
import os

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".weather_duty")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "service_key": "",
    "favorites": ["서울"],
}
# "branches"는 DEFAULT_CONFIG에 넣지 않는다 - 여기 넣으면 다른 설정을 한 번만
# 저장해도 파일에 "branches": {} 가 같이 기록되어, seed_default_branches_if_needed()가
# "이미 설정된 적 있음"으로 착각해 기본 지사 구성을 절대 못 채워 넣게 된다.

# 첫 실행 시 한 번만 시딩되는 지사 구성(사용자가 알려준 실제 관할 구조).
# 이후에는 "지사 관리" 화면에서 자유롭게 추가/수정/삭제한다.
DEFAULT_BRANCHES = {
    "진천": [
        "경기도 안성시", "경기도 이천시", "충청북도 음성군", "충청북도 진천군",
        "충청북도 청주시 상당구", "충청북도 청주시 서원구", "충청북도 청주시 청원구",
        "충청북도 청주시 흥덕구",
    ],
    "제천": ["강원특별자치도 원주시", "충청북도 단양군", "충청북도 제천시"],
    "충주": ["경기도 여주시", "충청북도 괴산군", "충청북도 음성군", "충청북도 충주시"],
    "보은": [
        "경상북도 상주시", "충청북도 보은군",
        "충청북도 청주시 상당구", "충청북도 청주시 서원구", "충청북도 청주시 청원구",
        "충청북도 청주시 흥덕구",
    ],
    "엄정": [
        "경기도 안성시", "충청북도 음성군", "충청북도 제천시", "충청북도 진천군",
        "충청북도 충주시",
    ],
    "상주": ["경상북도 구미시", "경상북도 문경시", "경상북도 상주시", "충청북도 괴산군"],
}


def load_config():
    if not os.path.exists(CONFIG_PATH):
        return dict(DEFAULT_CONFIG)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return dict(DEFAULT_CONFIG)
    merged = dict(DEFAULT_CONFIG)
    merged.update(data)
    return merged


def save_config(config):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_service_key():
    return load_config().get("service_key", "")


def set_service_key(key):
    config = load_config()
    config["service_key"] = key
    save_config(config)


def get_favorites():
    return load_config().get("favorites", [])


def set_favorites(favorites):
    config = load_config()
    config["favorites"] = favorites
    save_config(config)


def add_favorite(name):
    favorites = get_favorites()
    if name not in favorites:
        favorites.append(name)
        set_favorites(favorites)


def remove_favorite(name):
    favorites = get_favorites()
    if name in favorites:
        favorites.remove(name)
        set_favorites(favorites)


def get_branches():
    return load_config().get("branches", {})


def set_branches(branches):
    config = load_config()
    config["branches"] = branches
    save_config(config)


def add_branch(name):
    branches = get_branches()
    branches.setdefault(name, [])
    set_branches(branches)


def remove_branch(name):
    branches = get_branches()
    branches.pop(name, None)
    set_branches(branches)


def add_region_to_branch(branch, region_name):
    branches = get_branches()
    branches.setdefault(branch, [])
    if region_name not in branches[branch]:
        branches[branch].append(region_name)
    set_branches(branches)


def remove_region_from_branch(branch, region_name):
    branches = get_branches()
    if branch in branches and region_name in branches[branch]:
        branches[branch].remove(region_name)
        set_branches(branches)


def _raw_config_has_key(key):
    """DEFAULT_CONFIG 병합 없이, 사용자가 실제로 저장한 파일에 그 키가 있었는지만 본다."""
    if not os.path.exists(CONFIG_PATH):
        return False
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return False
    return key in data


def seed_default_branches_if_needed():
    """이 기능이 처음 추가된 버전을 처음 실행할 때 한 번만 기본 지사 구성을 채워 넣는다.
    이미 한 번이라도 저장된 적이 있으면(사용자가 다 지웠어도) 다시 건드리지 않는다."""
    if _raw_config_has_key("branches"):
        return
    set_branches(DEFAULT_BRANCHES)
    favorites = set(get_favorites())
    for region_names in DEFAULT_BRANCHES.values():
        favorites.update(region_names)
    set_favorites(sorted(favorites))
