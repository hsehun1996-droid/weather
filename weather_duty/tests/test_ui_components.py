"""ui_components.py의 순수 프레젠테이션 위젯 스모크 테스트.

여기서는 위젯이 값을 받아 올바르게 표시하는지, 그리고 라이트/다크 전환에
반응해 스타일을 다시 계산하는지만 확인한다. API 호출/저장 로직은 이 모듈에
아예 없으므로(=ui_components.py는 순수 표시 전용) 테스트 대상도 아니다.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402
from qfluentwidgets import FluentIcon, Theme, setTheme  # noqa: E402

from weather_duty import theme, ui_components as uic  # noqa: E402

_app = QApplication.instance() or QApplication([])


class ComponentSmokeTest(unittest.TestCase):
    def tearDown(self):
        setTheme(Theme.LIGHT)

    def test_status_pill_updates_text_and_tone(self):
        pill = uic.StatusPill("조회 중", tone="loading")
        self.assertEqual(pill._label.text(), "조회 중")
        pill.set_state(text="갱신 완료", tone="success")
        self.assertEqual(pill._label.text(), "갱신 완료")
        self.assertEqual(pill.property("tone"), "success")

    def test_tag_badge_updates_text_and_tone(self):
        badge = uic.TagBadge("실측", tone="info")
        badge.set_text_and_tone("중기예보", tone="neutral")
        self.assertEqual(badge.text(), "중기예보")
        self.assertEqual(badge.property("tone"), "neutral")

    def test_inline_banner_updates_message_and_level(self):
        banner = uic.InlineBanner("현재 발효 중인 특보 없음", level="success")
        banner.set_message("⚠ 특보 발효 중: 폭염주의보", level="danger")
        self.assertEqual(banner._text_label.text(), "⚠ 특보 발효 중: 폭염주의보")
        self.assertEqual(banner.property("level"), "danger")

    def test_section_header_title_and_subtitle(self):
        header = uic.SectionHeader("지난 실측 2일 + 향후 예보", subtitle="가져올 수 있는 최대 기간")
        header.set_title("예보")
        header.set_subtitle("갱신됨")
        self.assertEqual(header._title_label.text(), "예보")
        self.assertEqual(header._subtitle_label.text(), "갱신됨")

    def test_metric_block_updates_value_and_caption(self):
        block = uic.MetricBlock("27℃", "1시간 강수량 0mm")
        block.set_value("30℃")
        block.set_caption("1시간 강수량 3mm")
        self.assertEqual(block._value_label.text(), "30℃")
        self.assertEqual(block._caption_label.text(), "1시간 강수량 3mm")

    def test_empty_state_shows_title_and_description(self):
        empty = uic.EmptyState("즐겨찾기가 비어 있습니다.", "'즐겨찾기 편집'에서 추가하세요.")
        self.assertEqual(empty._title_label.text(), "즐겨찾기가 비어 있습니다.")
        self.assertEqual(empty._desc_label.text(), "'즐겨찾기 편집'에서 추가하세요.")

    def test_icon_action_button_has_fixed_footprint(self):
        btn = uic.IconActionButton(FluentIcon.SETTING, tooltip="설정")
        self.assertEqual(btn.width(), theme.CONTROL_HEIGHT_SMALL)
        self.assertEqual(btn.height(), theme.CONTROL_HEIGHT_SMALL)
        self.assertEqual(btn.toolTip(), "설정")

    def test_components_restyle_on_theme_change(self):
        setTheme(Theme.LIGHT)
        pill = uic.StatusPill("상태", tone="danger")
        style_light = pill.styleSheet()

        setTheme(Theme.DARK)
        QApplication.processEvents()
        style_dark = pill.styleSheet()

        self.assertNotEqual(style_light, style_dark)

    def test_component_can_be_garbage_collected(self):
        """컴포넌트가 theme.bind_theme_change로 테마 변경을 구독해도, 더 이상
        아무도 참조하지 않으면 정상적으로 가비지 컬렉션돼야 한다(전역 테마
        시그널이 컴포넌트를 영원히 붙잡아 메모리를 새게 하면 안 된다)."""
        import gc
        import weakref

        def _make():
            pill = uic.StatusPill("상태", tone="warning")
            return weakref.ref(pill)

        ref = _make()
        gc.collect()
        self.assertIsNone(ref())


class AccessibilityDefaultsTest(unittest.TestCase):
    """accessibleName이 최소한 tooltip/현재 상태 텍스트만큼은 자동으로
    채워지는지 확인한다 - 스크린리더가 아이콘만 있는 버튼/상태 배지를 읽을 수
    있으려면 필요하다."""

    def tearDown(self):
        setTheme(Theme.LIGHT)

    def test_status_pill_set_state_syncs_accessible_name(self):
        pill = uic.StatusPill("대기", tone="neutral")
        self.assertEqual(pill.accessibleName(), "대기")
        pill.set_state(text="조회 중", tone="info")
        self.assertEqual(pill.accessibleName(), "조회 중")

    def test_icon_action_button_accessible_name_defaults_to_tooltip(self):
        btn = uic.IconActionButton(FluentIcon.SETTING, tooltip="설정")
        self.assertEqual(btn.accessibleName(), "설정")

    def test_danger_hover_icon_button_accessible_name_defaults_to_tooltip(self):
        btn = uic.DangerHoverIconButton(FluentIcon.DELETE, tooltip="삭제")
        self.assertEqual(btn.accessibleName(), "삭제")


def _forecast_row_with_data(has_detail=True, disabled_reason=""):
    row = uic.ForecastRow()
    row.set_data(
        date_text="08/29(토)", condition_text="맑음", pop_text="30%", pop_tone="info",
        pcp_text="강수없음", feels_text="체감 19~30", source_text="단기예보", source_tone="neutral",
        temp_text="20 / 28", tooltip="맑음, 20~28도",
        has_detail=has_detail, disabled_reason=disabled_reason,
    )
    return row


class ForecastRowTest(unittest.TestCase):
    """ForecastRow(일별 예보 한 줄)의 접근성(키보드 활성화/비활성 상태)과
    반응형 레이아웃(정상/컴팩트 전환) 계약을 확인한다."""

    def tearDown(self):
        setTheme(Theme.LIGHT)

    def test_has_detail_enables_button_with_default_tooltip(self):
        row = _forecast_row_with_data(has_detail=True)
        btn = row._normal["button"]
        self.assertTrue(btn.isEnabled())
        self.assertEqual(btn.toolTip(), "상세보기")

    def test_no_detail_disables_button_with_reason_tooltip(self):
        row = _forecast_row_with_data(has_detail=False, disabled_reason="시간별 데이터가 없습니다.")
        btn = row._normal["button"]
        self.assertFalse(btn.isEnabled())
        self.assertEqual(btn.toolTip(), "시간별 데이터가 없습니다.")

    def test_keyboard_enter_activates_when_has_detail(self):
        from PySide6.QtCore import QEvent, Qt as _Qt
        from PySide6.QtGui import QKeyEvent

        row = _forecast_row_with_data(has_detail=True)
        fired = []
        row.activated.connect(lambda: fired.append(1))
        ev = QKeyEvent(QEvent.Type.KeyPress, _Qt.Key.Key_Return, _Qt.KeyboardModifier.NoModifier)
        row.keyPressEvent(ev)
        self.assertEqual(len(fired), 1)

    def test_keyboard_enter_does_not_activate_without_detail(self):
        from PySide6.QtCore import QEvent, Qt as _Qt
        from PySide6.QtGui import QKeyEvent

        row = _forecast_row_with_data(has_detail=False)
        fired = []
        row.activated.connect(lambda: fired.append(1))
        ev = QKeyEvent(QEvent.Type.KeyPress, _Qt.Key.Key_Return, _Qt.KeyboardModifier.NoModifier)
        row.keyPressEvent(ev)
        self.assertEqual(len(fired), 0)

    def test_double_click_always_emits_regardless_of_has_detail(self):
        """더블클릭(기존 동작)은 has_detail=False인 행(중기예보 등)에서도
        그대로 다이얼로그를 열 수 있어야 한다 - 다이얼로그 자체가 "시간별
        데이터 없음" 안내를 보여주는 몫이라, 더블클릭까지 막을 이유가 없다."""
        from PySide6.QtCore import QEvent, QPointF, Qt as _Qt
        from PySide6.QtGui import QMouseEvent

        row = _forecast_row_with_data(has_detail=False)
        fired = []
        row.doubleClicked.connect(lambda: fired.append(1))
        ev = QMouseEvent(
            QEvent.Type.MouseButtonDblClick, QPointF(5, 5), QPointF(5, 5), _Qt.MouseButton.LeftButton,
            _Qt.MouseButton.LeftButton, _Qt.KeyboardModifier.NoModifier,
        )
        row.mouseDoubleClickEvent(ev)
        self.assertEqual(len(fired), 1)

    def test_responsive_breakpoint_normal_at_760(self):
        row = _forecast_row_with_data()
        row.resize(theme.FORECAST_ROW_COMPACT_BREAKPOINT, row.height() or 64)
        row._apply_mode(compact=row.contentsRect().width() < theme.FORECAST_ROW_COMPACT_BREAKPOINT)
        self.assertFalse(row._is_compact)
        self.assertEqual(row.height(), theme.FORECAST_ROW_HEIGHT)

    def test_responsive_breakpoint_compact_at_759(self):
        row = _forecast_row_with_data()
        row.resize(theme.FORECAST_ROW_COMPACT_BREAKPOINT - 1, row.height() or 64)
        row._apply_mode(compact=row.contentsRect().width() < theme.FORECAST_ROW_COMPACT_BREAKPOINT)
        self.assertTrue(row._is_compact)
        self.assertEqual(row.height(), theme.FORECAST_ROW_HEIGHT_COMPACT)

    def test_compact_mode_reuses_same_widgets_not_recreated(self):
        """resizeEvent가 위젯을 새로 만드는 게 아니라 미리 만든 두 페이지
        (QStackedLayout) 중 하나만 보여주는지 확인 - 페이지 위젯 identity가
        전환 전후로 그대로여야 한다."""
        row = _forecast_row_with_data()
        normal_page_before = row._normal["page"]
        compact_page_before = row._compact["page"]
        row._apply_mode(compact=True)
        row._apply_mode(compact=False)
        self.assertIs(row._normal["page"], normal_page_before)
        self.assertIs(row._compact["page"], compact_page_before)


if __name__ == "__main__":
    unittest.main()
