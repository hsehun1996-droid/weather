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


if __name__ == "__main__":
    unittest.main()
