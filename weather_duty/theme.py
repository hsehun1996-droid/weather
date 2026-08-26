"""애플 시스템 색상(그레이스케일 "Graphite" 악센트)에 맞춘 라이트/다크 팔레트.

라이트/다크 자동 전환과 강조색 파생은 qfluentwidgets(PySide6-Fluent-Widgets)가
맡고, 이 모듈은 qfluentwidgets가 다루지 않는 의미색(경고/정상/위험도, 버튼
텍스트색 등)만 우리 앱 전용으로 추가 정의한다. 강조색 자체도 파란색이 아니라
macOS 시스템 설정의 "그래파이트"(무채색) 손잡이색과 같은 중성 회색을 쓴다 -
채도가 있는 색보다 흑백톤 요청에 더 맞고, 순수 검정처럼 다크 모드 배경에
묻히지도 않는다.
"""
import os

from PySide6.QtGui import QFont, QFontDatabase
from qfluentwidgets import Theme, isDarkTheme, qconfig, setTheme, setThemeColor

_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
_FONTS_DIR = os.path.join(_ASSETS_DIR, "fonts")

GRAPHITE_ACCENT = "#8E8E93"

LIGHT = dict(
    bg="#F2F2F7", card="#FFFFFF", card_hover="#E9E9EE", text="#1C1C1E",
    subtext="#6E6E73", accent="#1C1C1E", warn_bg="#FFEBEA", warn_text="#D70015",
    ok_bg="#EAF7ED", ok_text="#1D7A34", border="#D1D1D6",
    risk_high="#D70015", risk_mid="#B25000", on_accent="#FFFFFF",
)
DARK = dict(
    bg="#000000", card="#1C1C1E", card_hover="#2C2C2E", text="#F5F5F7",
    subtext="#98989D", accent="#E5E5EA", warn_bg="#3A1F1E", warn_text="#FF6961",
    ok_bg="#1F3324", ok_text="#30D158", border="#38383A",
    risk_high="#FF6961", risk_mid="#FFB340", on_accent="#000000",
)

FONT_FAMILY = "Pretendard"
_FALLBACK_FAMILIES = ["Malgun Gothic", "Apple SD Gothic Neo", "Segoe UI", "sans-serif"]


def init_app_theme():
    """qfluentwidgets 전역 테마를 설정한다. 앱 시작 시 한 번만 호출."""
    setTheme(Theme.AUTO)
    setThemeColor(GRAPHITE_ACCENT)


def colors():
    return DARK if isDarkTheme() else LIGHT


def on_theme_changed(slot):
    """라이트/다크 전환(OS 설정 변경 포함)을 감지해 slot()을 호출하도록 등록."""
    qconfig.themeChanged.connect(lambda _theme: slot())


def load_bundled_fonts():
    """Pretendard 정적 폰트(Regular/Medium/SemiBold/Bold)를 앱에 등록한다.
    파일이 없거나 로딩에 실패해도 조용히 넘어가고, 이후 FONT_FAMILY 지정은
    시스템 폰트로 자연스럽게 대체된다."""
    if not os.path.isdir(_FONTS_DIR):
        return
    for filename in (
        "Pretendard-Regular.otf",
        "Pretendard-Medium.otf",
        "Pretendard-SemiBold.otf",
        "Pretendard-Bold.otf",
    ):
        path = os.path.join(_FONTS_DIR, filename)
        if os.path.exists(path):
            QFontDatabase.addApplicationFont(path)


def font(size, weight=QFont.Weight.Normal):
    families = [FONT_FAMILY] + _FALLBACK_FAMILIES
    f = QFont(families, size)
    f.setWeight(weight)
    return f


def pop_color(pop, c):
    """강수확률에 따른 강조 색(적당히 높으면 경고색으로)."""
    if pop is None:
        return c["subtext"]
    if pop >= 70:
        return c["risk_high"]
    if pop >= 50:
        return c["risk_mid"]
    return c["text"]
