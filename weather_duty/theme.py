"""Calm Operations Dashboard 디자인 토큰: 색상 / 간격 / 반경 / 크기 / 타이포그래피.

라이트·다크 모드 자동 전환과 강조색 파생 자체는 qfluentwidgets(PySide6-Fluent-Widgets)가
맡고, 이 모듈은 그 위에 앱 전용 디자인 토큰(색상 팔레트, 여백/반경/크기 스케일,
타이포그래피 역할)을 얹어 GUI 코드가 하드코딩된 숫자·색상 대신 이름 있는 토큰을
쓰도록 중앙화한다.

하위 호환성: 예전 theme.py는 색상 키가 bg/card/text/subtext/... 처럼 짧은 이름이었다.
`colors()`가 반환하는 dict에는 새 토큰(예: background/surface/text_primary)과
이 예전 키들이 "별칭"으로 함께 들어 있으므로, 기존 gui.py의 `c["bg"]`, `c["card"]`
같은 호출은 코드를 한 줄도 바꾸지 않아도 계속 동작한다. `font()`/`pop_color()`
시그니처도 그대로 유지된다.
"""
import os

from PySide6.QtGui import QFont, QFontDatabase
from qfluentwidgets import Theme, isDarkTheme, qconfig, setTheme, setThemeColor

_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
_FONTS_DIR = os.path.join(_ASSETS_DIR, "fonts")

# ---------------------------------------------------------------------------
# 색상 토큰
# ---------------------------------------------------------------------------
# accent는 선택/포커스/주요 행동/링크에만, success/warning/danger는 실제 상태
# 의미에 맞게만 쓴다("최다 강수 지역"처럼 단순 강조 목적으로 danger를 쓰지 않는다).
# 다크 모드 배경도 순수 검정(#000000)이 아니라 은은한 네이비 계열을 쓴다.

LIGHT = dict(
    background="#F5F7FA", surface="#FFFFFF", surface_alt="#F0F3F7",
    surface_elevated="#FFFFFF", surface_hover="#EAF0F6", surface_pressed="#E2E8F0",
    surface_selected="#EAF0FF",
    border_subtle="#E3E8EF", border_strong="#C9D2DE", divider="#E8ECF2",
    text_primary="#17202A", text_secondary="#5E6B7A", text_tertiary="#8793A2",
    text_disabled="#B2BBC7", text_inverse="#FFFFFF",
    accent="#4F6BED", accent_hover="#4058C7", accent_pressed="#344AB3",
    accent_soft="#EEF2FF", on_accent="#FFFFFF", focus="#4F6BED",
    success="#1F8A5B", success_soft="#EAF8F1",
    warning="#B87503", warning_soft="#FFF5DE",
    danger="#D64545", danger_soft="#FDECEC",
    info="#2F6FED", info_soft="#EAF2FF",
    overlay="rgba(15, 23, 42, 0.42)",
)

DARK = dict(
    background="#0E1116", surface="#151A22", surface_alt="#1B222C",
    surface_elevated="#1C222C", surface_hover="#232B36", surface_pressed="#2B3542",
    surface_selected="#1D2B50",
    border_subtle="#2A3340", border_strong="#3B4655", divider="#252E39",
    text_primary="#F3F5F7", text_secondary="#ADB6C2", text_tertiary="#7E8998",
    text_disabled="#596575", text_inverse="#0E1116",
    accent="#7C9CFF", accent_hover="#93AEFF", accent_pressed="#6688EF",
    accent_soft="#1B2A4D", on_accent="#0E1116", focus="#8AA8FF",
    success="#5BC89A", success_soft="#143429",
    warning="#E8B45A", warning_soft="#3A2B12",
    danger="#FF7A7A", danger_soft="#421F24",
    info="#82A8FF", info_soft="#1A2B49",
    overlay="rgba(0, 0, 0, 0.58)",
)

# 예전 theme.py가 쓰던 색상 키 -> 새 토큰 키. gui.py의 실제 c["..."] 사용처를
# 전수 조사(grep)해서 나온 키만 담았다: bg, card, card_hover, text, subtext,
# accent, warn_bg, warn_text, ok_bg, ok_text, border, risk_high, risk_mid, on_accent.
# accent/on_accent는 예전과 새 토큰의 키 이름 자체가 같아서 별도 별칭이 필요 없다.
_LEGACY_ALIASES = {
    "bg": "background",
    "card": "surface",
    "card_hover": "surface_hover",
    "text": "text_primary",
    "subtext": "text_secondary",
    "border": "border_subtle",
    "warn_bg": "warning_soft",
    "warn_text": "warning",
    "ok_bg": "success_soft",
    "ok_text": "success",
    "risk_high": "danger",
    "risk_mid": "warning",
}


def _with_legacy_aliases(tokens):
    resolved = dict(tokens)
    for old_key, new_key in _LEGACY_ALIASES.items():
        resolved[old_key] = tokens[new_key]
    return resolved


# 렌더링마다(각 _render_* 호출마다) 다시 만들 필요 없이 모듈 로드 시 한 번만 계산한다.
_LIGHT_RESOLVED = _with_legacy_aliases(LIGHT)
_DARK_RESOLVED = _with_legacy_aliases(DARK)

ACCENT_SEED = LIGHT["accent"]


# ---------------------------------------------------------------------------
# 간격 토큰 (기본 그리드 4px)
# ---------------------------------------------------------------------------

SPACE_0 = 0
SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 20
SPACE_6 = 24
SPACE_8 = 32
SPACE_10 = 40
SPACE_12 = 48

# ---------------------------------------------------------------------------
# 모서리 반경 토큰
# ---------------------------------------------------------------------------

RADIUS_SMALL = 6
RADIUS_CONTROL = 8
RADIUS_PANEL = 12
RADIUS_CARD = 14
RADIUS_DIALOG = 18
RADIUS_PILL = 999

# ---------------------------------------------------------------------------
# 컨트롤/레이아웃 크기 토큰
# ---------------------------------------------------------------------------

CONTROL_HEIGHT_COMPACT = 30
CONTROL_HEIGHT_SMALL = 32
CONTROL_HEIGHT_DEFAULT = 38
CONTROL_HEIGHT_LARGE = 44

ICON_SIZE_SMALL = 14
ICON_SIZE_DEFAULT = 18
ICON_SIZE_LARGE = 20

HEADER_HEIGHT = 64
FORECAST_ROW_HEIGHT = 64
TABLE_HEADER_HEIGHT = 40
TABLE_ROW_HEIGHT = 44

SIDEBAR_MIN_WIDTH = 220
SIDEBAR_DEFAULT_WIDTH = 236
SIDEBAR_MAX_WIDTH = 280

APP_CONTENT_MARGIN = 24
CARD_PADDING = 20
DIALOG_CONTENT_MARGIN = 24

# 키보드 포커스 링 두께("2px accent/focus 색상으로 명확히 표시").
FOCUS_RING_WIDTH = 2

# ---------------------------------------------------------------------------
# 타이포그래피
# ---------------------------------------------------------------------------

FONT_FAMILY = "Pretendard"
_FALLBACK_FAMILIES = ["Malgun Gothic", "Apple SD Gothic Neo", "Segoe UI", "sans-serif"]

# (size, weight) - 전부 QFont.Weight.DemiBold/Medium/Normal만 쓰고 Bold는 쓰지
# 않는다("모든 텍스트를 Bold로 만들지 말 것", 큰 제목=DemiBold, 버튼/라벨=Medium).
TYPOGRAPHY = {
    "metric_display": (42, QFont.Weight.DemiBold),
    "page_title": (24, QFont.Weight.DemiBold),
    "section_title": (18, QFont.Weight.DemiBold),
    "card_title": (15, QFont.Weight.DemiBold),
    "body": (14, QFont.Weight.Normal),
    "body_medium": (14, QFont.Weight.Medium),
    "label": (13, QFont.Weight.Medium),
    "caption": (12, QFont.Weight.Normal),
    "micro": (11, QFont.Weight.Medium),
}


def init_app_theme():
    """qfluentwidgets 전역 테마를 설정한다. 앱 시작 시 한 번만 호출."""
    setTheme(Theme.AUTO)
    setThemeColor(ACCENT_SEED)


def colors():
    """현재 라이트/다크 모드에 맞는 색상 토큰 dict를 반환한다.
    새 토큰(background, surface, text_primary, ...)과 예전 키(bg, card, text, ...)가
    같은 값으로 함께 들어 있어 신규/기존 호출부 어느 쪽에서 조회해도 안전하다."""
    return _DARK_RESOLVED if isDarkTheme() else _LIGHT_RESOLVED


def on_theme_changed(slot):
    """라이트/다크 전환(OS 설정 변경 포함)을 감지해 slot()을 호출하도록 등록.
    연결 해제를 신경 쓰지 않는 앱 수명 전체의 싱글턴(WeatherDutyApp)에 적합하다.
    반복 생성/파괴되는 위젯에는 `bind_theme_change()`를 대신 쓴다."""
    qconfig.themeChanged.connect(lambda _theme: slot())


def bind_theme_change(widget, slot):
    """`on_theme_changed`와 같지만, widget이 파괴되면 연결을 자동으로 끊는다.
    ui_components.py의 위젯들처럼 반복적으로 만들어졌다 사라질 수 있는 경우,
    이 함수를 안 쓰면 이미 삭제된 위젯을 가리키는 콜백이 전역 테마 시그널에
    계속 남아 있다가 다음 테마 전환 때 "이미 삭제된 C++ 객체" 오류로 이어질 수 있다.

    widget과 slot(보통 widget의 바운드 메서드, 예: self._refresh_style)을 직접
    붙잡으면 전역 qconfig.themeChanged가 widget을 영원히 살려 놓아 애초에
    없애려던 문제(안 쓰는 위젯이 계속 메모리에 남는 것)를 오히려 만들어내므로,
    둘 다 약한 참조(weakref)로만 들고 있는다. 거기에 더해, widget이 실제로
    언제 파괴되는지(deleteLater 이후 이벤트 루프 타이밍)는 보장하기 어려우므로
    destroyed 시그널로 연결 해제를 시도하는 것과 별개로 slot 호출 직전
    shiboken6.isValid(widget)로 한 번 더 방어한다."""
    import weakref

    widget_ref = weakref.ref(widget)
    slot_ref = weakref.WeakMethod(slot) if hasattr(slot, "__self__") else (lambda: slot)

    def _on_theme_changed(_theme=None):
        target = widget_ref()
        if target is None:
            return
        try:
            import shiboken6
            if not shiboken6.isValid(target):
                return
        except ImportError:
            pass
        bound_slot = slot_ref()
        if bound_slot is not None:
            bound_slot()

    qconfig.themeChanged.connect(_on_theme_changed)

    def _disconnect():
        try:
            qconfig.themeChanged.disconnect(_on_theme_changed)
        except (RuntimeError, TypeError):
            pass  # 이미 해제됐거나 시그널 소스가 먼저 사라진 경우 - 조용히 무시.

    widget.destroyed.connect(_disconnect)


def set_dynamic_property(widget, name, value):
    """dynamic property를 갱신하고, 그 값에 의존하는 QSS 선택자가 즉시 다시
    적용되도록 unpolish/polish를 안전하게 수행한다(스타일시트 자체를 새로
    만들어 setStyleSheet()를 반복 호출하는 대신, 상태만 바꾸는 용도)."""
    widget.setProperty(name, value)
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


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


def font_role(role):
    """TYPOGRAPHY에 정의된 이름 있는 역할(metric_display/page_title/... )로
    QFont를 만든다. `font(size, weight)`는 계속 그대로 쓸 수 있다."""
    size, weight = TYPOGRAPHY[role]
    return font(size, weight)


def pop_color(pop, c):
    """강수확률에 따른 강조 색(적당히 높으면 경고색으로)."""
    if pop is None:
        return c["subtext"]
    if pop >= 70:
        return c["risk_high"]
    if pop >= 50:
        return c["risk_mid"]
    return c["text"]
