"""디자인 시스템 토큰(색상/간격/반경/크기/타이포그래피) 회귀 테스트.

여기서는 theme.py가 노출하는 값 자체만 검증한다. 기상청 API 호출, config.json
저장 같은 비즈니스 로직은 이 테스트의 대상이 아니다(해당 로직은
test_kma_client.py / test_regions.py에서 이미 다룬다).
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from qfluentwidgets import Theme, setTheme  # noqa: E402

from weather_duty import theme  # noqa: E402

# QFont 생성에는 QApplication 인스턴스가 있어야 폰트 백엔드가 안전하게 동작한다.
_app = QApplication.instance() or QApplication([])

# 예전 theme.py가 쓰던 색상 키(gui.py의 실제 c["..."] 사용처 전수 조사 결과).
_LEGACY_COLOR_KEYS = [
    "bg", "card", "card_hover", "text", "subtext", "accent",
    "warn_bg", "warn_text", "ok_bg", "ok_text", "border",
    "risk_high", "risk_mid", "on_accent",
]

_NEW_COLOR_KEYS = [
    "background", "surface", "surface_alt", "surface_elevated", "surface_hover",
    "surface_pressed", "surface_selected",
    "border_subtle", "border_strong", "divider",
    "text_primary", "text_secondary", "text_tertiary", "text_disabled", "text_inverse",
    "accent", "accent_hover", "accent_pressed", "accent_soft", "on_accent", "focus",
    "success", "success_soft", "warning", "warning_soft", "danger", "danger_soft",
    "info", "info_soft", "overlay",
]

_SPACE_TOKENS = {
    "SPACE_0": 0, "SPACE_1": 4, "SPACE_2": 8, "SPACE_3": 12, "SPACE_4": 16,
    "SPACE_5": 20, "SPACE_6": 24, "SPACE_8": 32, "SPACE_10": 40, "SPACE_12": 48,
}

_RADIUS_TOKENS = {
    "RADIUS_SMALL": 6, "RADIUS_CONTROL": 8, "RADIUS_PANEL": 12,
    "RADIUS_CARD": 14, "RADIUS_DIALOG": 18, "RADIUS_PILL": 999,
}

_SIZE_TOKENS = {
    "CONTROL_HEIGHT_COMPACT": 30, "CONTROL_HEIGHT_SMALL": 32,
    "CONTROL_HEIGHT_DEFAULT": 38, "CONTROL_HEIGHT_LARGE": 44,
    "ICON_SIZE_SMALL": 14, "ICON_SIZE_DEFAULT": 18, "ICON_SIZE_LARGE": 20,
    "HEADER_HEIGHT": 64, "FORECAST_ROW_HEIGHT": 64,
    "TABLE_HEADER_HEIGHT": 40, "TABLE_ROW_HEIGHT": 44,
    "SIDEBAR_MIN_WIDTH": 220, "SIDEBAR_DEFAULT_WIDTH": 236, "SIDEBAR_MAX_WIDTH": 280,
    "APP_CONTENT_MARGIN": 24, "CARD_PADDING": 20, "DIALOG_CONTENT_MARGIN": 24,
}

_TYPOGRAPHY_EXPECTED = {
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


class ColorTokenTest(unittest.TestCase):
    def tearDown(self):
        setTheme(Theme.LIGHT)

    def test_light_and_dark_expose_all_new_tokens(self):
        for key in _NEW_COLOR_KEYS:
            self.assertIn(key, theme.LIGHT, key)
            self.assertIn(key, theme.DARK, key)

    def test_colors_contains_all_legacy_keys(self):
        setTheme(Theme.LIGHT)
        c = theme.colors()
        for key in _LEGACY_COLOR_KEYS:
            self.assertIn(key, c, key)

    def test_legacy_keys_alias_to_new_tokens_light(self):
        setTheme(Theme.LIGHT)
        c = theme.colors()
        for old_key, new_key in theme._LEGACY_ALIASES.items():
            self.assertEqual(c[old_key], theme.LIGHT[new_key], old_key)

    def test_legacy_keys_alias_to_new_tokens_dark(self):
        setTheme(Theme.DARK)
        c = theme.colors()
        for old_key, new_key in theme._LEGACY_ALIASES.items():
            self.assertEqual(c[old_key], theme.DARK[new_key], old_key)

    def test_accent_and_on_accent_unaliased_keys_still_present(self):
        # accent/on_accent는 새/구 토큰의 키 이름이 같아 별도 별칭 없이도 존재해야 한다.
        setTheme(Theme.LIGHT)
        c = theme.colors()
        self.assertEqual(c["accent"], theme.LIGHT["accent"])
        self.assertEqual(c["on_accent"], theme.LIGHT["on_accent"])

    def test_dark_background_is_not_pure_black(self):
        self.assertNotEqual(theme.DARK["background"].upper(), "#000000")

    def test_light_and_dark_differ(self):
        setTheme(Theme.LIGHT)
        light = theme.colors()
        setTheme(Theme.DARK)
        dark = theme.colors()
        self.assertEqual(set(light.keys()), set(dark.keys()))
        self.assertNotEqual(light["background"], dark["background"])


class SpacingRadiusSizeTokenTest(unittest.TestCase):
    def test_spacing_tokens(self):
        for name, expected in _SPACE_TOKENS.items():
            self.assertEqual(getattr(theme, name), expected, name)

    def test_radius_tokens(self):
        for name, expected in _RADIUS_TOKENS.items():
            self.assertEqual(getattr(theme, name), expected, name)

    def test_size_tokens(self):
        for name, expected in _SIZE_TOKENS.items():
            self.assertEqual(getattr(theme, name), expected, name)


class TypographyTest(unittest.TestCase):
    def test_typography_roles_match_spec(self):
        for role, (size, weight) in _TYPOGRAPHY_EXPECTED.items():
            f = theme.font_role(role)
            self.assertEqual(f.pointSize(), size, role)
            self.assertEqual(f.weight(), weight, role)

    def test_font_backward_compatible(self):
        f = theme.font(13, QFont.Weight.Normal)
        self.assertEqual(f.pointSize(), 13)
        self.assertEqual(f.weight(), QFont.Weight.Normal)

        f_default_weight = theme.font(46)
        self.assertEqual(f_default_weight.weight(), QFont.Weight.Normal)

    def test_font_uses_pretendard_family_first(self):
        f = theme.font(14)
        self.assertEqual(f.families()[0], theme.FONT_FAMILY)


class PopColorTest(unittest.TestCase):
    def test_thresholds_unchanged(self):
        c = theme.colors()
        self.assertEqual(theme.pop_color(80, c), c["risk_high"])
        self.assertEqual(theme.pop_color(70, c), c["risk_high"])
        self.assertEqual(theme.pop_color(60, c), c["risk_mid"])
        self.assertEqual(theme.pop_color(50, c), c["risk_mid"])
        self.assertEqual(theme.pop_color(30, c), c["text"])
        self.assertEqual(theme.pop_color(None, c), c["subtext"])


class ThemeChangeBindingTest(unittest.TestCase):
    """반복 생성/파괴되는 위젯이 위젯 파괴 후에도 죽은 콜백을 호출하지
    않는지(=bind_theme_change의 자동 연결 해제), 그리고 그 연결 자체가
    위젯을 붙잡아 두어 가비지 컬렉션을 막지 않는지 확인."""

    def test_bind_theme_change_stops_after_widget_destroyed(self):
        import gc

        from PySide6.QtWidgets import QWidget
        from qfluentwidgets import Theme as _Theme, qconfig

        calls = []

        def _make_and_bind():
            widget = QWidget()
            theme.bind_theme_change(widget, lambda: calls.append(1))
            return widget

        widget = _make_and_bind()
        qconfig.themeChanged.emit(_Theme.DARK)
        self.assertEqual(len(calls), 1)

        # 실제로 파괴돼야(가비지 컬렉션) 의미가 있다 - bind_theme_change가
        # widget/slot을 강하게 붙잡고 있으면 여기서 없어지지 않고, 그러면
        # 이 컴포넌트들은 전역 테마 시그널에 영원히 남아 메모리가 샌다.
        del widget
        gc.collect()

        qconfig.themeChanged.emit(_Theme.LIGHT)
        self.assertEqual(len(calls), 1)

    def test_bind_theme_change_does_not_keep_widget_alive(self):
        import gc
        import weakref

        from PySide6.QtWidgets import QWidget

        def _make():
            widget = QWidget()
            theme.bind_theme_change(widget, lambda: None)
            return widget, weakref.ref(widget)

        widget, ref = _make()
        del widget
        gc.collect()
        self.assertIsNone(ref(), "bind_theme_change가 widget을 강하게 참조해 GC를 막고 있다")


if __name__ == "__main__":
    unittest.main()
