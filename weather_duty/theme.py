"""애플 시스템 색상에 맞춘 라이트/다크 팔레트와 Pretendard 폰트 로딩.

customtkinter 시절 gui.py 맨 위에 있던 COLOR_* 튜플들을 Qt용으로 옮긴 것이다.
Qt는 위젯이 (light, dark) 튜플을 알아서 못 바꿔주므로, 테마가 바뀌면
호출부에서 다시 그려야 한다(ThemeManager.changed 시그널 참고).
"""
import os

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication

_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
_FONTS_DIR = os.path.join(_ASSETS_DIR, "fonts")

LIGHT = dict(
    bg="#F2F2F7", card="#FFFFFF", card_hover="#E9E9EE", text="#1C1C1E",
    subtext="#6E6E73", accent="#007AFF", warn_bg="#FFEBEA", warn_text="#FF3B30",
    ok_bg="#EAF7ED", ok_text="#34A853", border="#D1D1D6",
    risk_high="#D70015", risk_mid="#C77700", on_accent="#FFFFFF",
    shadow="#00000022",
)
DARK = dict(
    bg="#1C1C1E", card="#2C2C2E", card_hover="#3A3A3C", text="#F5F5F7",
    subtext="#98989D", accent="#0A84FF", warn_bg="#3A1F1E", warn_text="#FF453A",
    ok_bg="#1F3324", ok_text="#30D158", border="#3A3A3C",
    risk_high="#FF453A", risk_mid="#FF9F0A", on_accent="#FFFFFF",
    shadow="#00000055",
)

FONT_FAMILY = "Pretendard"
_FALLBACK_FAMILIES = ["Malgun Gothic", "Apple SD Gothic Neo", "Segoe UI", "sans-serif"]


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


def pop_color(pop, colors):
    """강수확률에 따른 강조 색(적당히 높으면 경고색으로)."""
    if pop is None:
        return colors["subtext"]
    if pop >= 70:
        return colors["risk_high"]
    if pop >= 50:
        return colors["risk_mid"]
    return colors["accent"]


class ThemeManager(QObject):
    """OS 라이트/다크 모드 변경을 감지해서 팔레트를 바꿔주는 얇은 래퍼.
    Qt 6.5+ 에서만 자동 감지가 되고, 그 이전 버전에서는 라이트로 고정된다."""

    changed = Signal()

    def __init__(self):
        super().__init__()
        self._dark = self._detect_dark()
        style_hints = QGuiApplication.styleHints()
        if hasattr(style_hints, "colorSchemeChanged"):
            style_hints.colorSchemeChanged.connect(self._on_scheme_changed)

    @staticmethod
    def _detect_dark():
        style_hints = QGuiApplication.styleHints()
        color_scheme = getattr(style_hints, "colorScheme", None)
        if color_scheme is None:
            return False
        try:
            from PySide6.QtCore import Qt
            return color_scheme() == Qt.ColorScheme.Dark
        except Exception:  # noqa: BLE001
            return False

    def _on_scheme_changed(self, _scheme):
        is_dark = self._detect_dark()
        if is_dark != self._dark:
            self._dark = is_dark
            self.changed.emit()

    @property
    def colors(self):
        return DARK if self._dark else LIGHT
