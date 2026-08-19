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
