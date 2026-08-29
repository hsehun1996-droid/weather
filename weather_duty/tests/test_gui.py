"""gui.py(WeatherDutyApp/다이얼로그)에 대한 스모크·회귀 테스트.

목(mock) 데이터만 쓰고 실제 기상청 API를 호출하지 않는다. 사용자의 실제
~/.weather_duty/config.json도 절대 건드리지 않도록, 모듈이 로드되는 시점에
config 모듈이 보는 저장 위치를 프로세스 전용 임시 디렉터리로 바꿔치기한다
(tools/gui_review.py와 같은 방식). WeatherDutyApp.__init__()이 매번 부르는
config.seed_default_branches_if_needed()가 빈 임시 config에서 DEFAULT_BRANCHES
(실제 관할 구성)를 즐겨찾기에 섞어 넣지 않도록, 미리 빈 branches를 한 번
저장해 둔다.
"""
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402
from qfluentwidgets import LineEdit, Theme, setTheme  # noqa: E402

from weather_duty import config  # noqa: E402

_TMP_CONFIG_DIR = tempfile.mkdtemp(prefix="weather_duty_test_gui_config_")
config.CONFIG_DIR = _TMP_CONFIG_DIR
config.CONFIG_PATH = os.path.join(_TMP_CONFIG_DIR, "config.json")
config.set_branches({})
# 즐겨찾기 종합보기(_render_summary)는 config.get_service_key()가 비어 있으면
# 실제 데이터 유무와 무관하게 "서비스키 설정이 필요합니다" 상태로 빠진다 -
# 이 임시 config에 진짜 API를 절대 호출하지 않는 가짜 문자열을 채워 둔다
# (모든 테스트가 window.reports를 직접 채우고 refresh_all()도 막아 둔다).
config.set_service_key("MOCK-TEST-KEY-NOT-A-REAL-KEY")

from weather_duty import gui, theme  # noqa: E402

_app = QApplication.instance() or QApplication([])


def tearDownModule():
    shutil.rmtree(_TMP_CONFIG_DIR, ignore_errors=True)


def _dispose(widget):
    """테스트에서 만든 위젯을 실제로 C++ 레벨까지 파괴한다. close()만으로는
    (WA_DeleteOnClose 없이는) 위젯이 숨겨지기만 할 뿐 살아 있어서, theme.py의
    bind_theme_change()가 widget.destroyed 시그널을 기다리며 걸어 둔 테마 전환
    구독 해제가 절대 일어나지 않는다 - 이 프로세스 안에서 만드는 위젯마다
    쌓이면 이후 모든 setTheme() 호출이 점점 느려진다(실제 앱은 메인 이벤트
    루프(app.exec())가 유휴 시간에 DeferredDelete를 알아서 처리해 문제되지
    않는다 - QApplication.processEvents()만으로는 DeferredDelete가 비워지지
    않는, 오프스크린 테스트 하네스에 한정된 현상)."""
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _app.processEvents()


def _hourly():
    return [
        {"time": f"{h:02d}00", "temp": "20", "feels_like": 19, "pop": 10,
         "pcp": "강수없음", "condition": "구름많음"}
        for h in range(0, 24, 3)
    ]


def _report(name, source="단기예보", hourly=True, errors=None):
    hourly_data = _hourly() if hourly else []
    return {
        "name": name,
        "current": {"temp": "27", "rain_1h": "0", "obs_time": "2026-08-29 09:00"},
        "forecast": [
            {"date": "20260829", "tmin": "20", "tmax": "28", "pop": 30, "pcp": "강수없음",
             "condition": "맑음", "source": source, "feels_like_min": 19, "feels_like_max": 30,
             "hourly": hourly_data},
        ],
        "warnings": [],
        "errors": errors or [],
    }


def _new_window():
    window = gui.WeatherDutyApp()
    window.refresh_all = lambda: None  # 시작 200ms 타이머의 실제 조회 시도 차단
    return window


def _fake_dialog_parent():
    """다이얼로그(AddBranchDialog/BranchManagerDialog 등)를 단독으로 테스트할
    때 쓰는 가벼운 부모 위젯 - 진짜 WeatherDutyApp()을 매번 새로 만들면
    SystemThemeListener(실제 OS 폴링 QThread)가 테스트마다 하나씩 새로
    시작/종료되어(종료 대기가 각각 실측 가능한 시간이 걸림) 테스트 스위트
    전체가 눈에 띄게 느려진다 - 다이얼로그가 실제로 쓰는 parent.font_body/
    parent.font_small만 채운 QWidget이면 충분하다."""
    from PySide6.QtWidgets import QWidget

    parent = QWidget()
    parent.font_body = theme.font(13)
    parent.font_small = theme.font(11)
    return parent


class MainWindowStateTest(unittest.TestCase):
    """Section 11: 테마 전환(_rebuild_ui) 전후로 스플리터 크기/포커스/종합표
    컬럼 폭이 유지되는지, view_mode만 복원하고 끝나지 않는지 확인한다."""

    def setUp(self):
        config.set_favorites(["충청북도 진천군"])
        self.window = _new_window()
        self.window.reports = {"충청북도 진천군": _report("충청북도 진천군")}
        self.window.selected_region = "충청북도 진천군"
        self.window._refresh_current_view()
        self.window.show()
        _app.processEvents()

    def tearDown(self):
        _dispose(self.window)
        setTheme(Theme.LIGHT)
        _app.processEvents()

    def test_theme_change_preserves_splitter_sizes(self):
        self.window._body_splitter.setSizes([300, self.window.width() - 300])
        _app.processEvents()
        before = self.window._body_splitter.sizes()

        self.window._on_theme_changed()
        _app.processEvents()

        self.assertEqual(self.window._body_splitter.sizes(), before)

    def test_theme_change_preserves_focus_on_favorites_list(self):
        self.window._render_favorite_list(config.get_favorites())
        _app.processEvents()
        self.window.favorites_list.setFocus()
        _app.processEvents()
        self.assertTrue(self.window.favorites_list.hasFocus())

        self.window._on_theme_changed()
        _app.processEvents()

        self.assertTrue(self.window.favorites_list.hasFocus())

    def test_theme_change_preserves_summary_column_width(self):
        self.window.summary_table.setColumnWidth(0, 140)
        self.window._on_theme_changed()
        _app.processEvents()
        self.assertEqual(self.window.summary_table.columnWidth(0), 140)

    def test_theme_change_preserves_view_mode_and_selected_region(self):
        self.window._set_view_mode("summary")
        _app.processEvents()
        self.window._on_theme_changed()
        _app.processEvents()
        self.assertEqual(self.window.view_mode, "summary")
        self.assertEqual(self.window.selected_region, "충청북도 진천군")


class SidebarCollapseTest(unittest.TestCase):
    def setUp(self):
        config.set_favorites(["충청북도 진천군"])
        self.window = _new_window()

    def tearDown(self):
        _dispose(self.window)
        setTheme(Theme.LIGHT)
        _app.processEvents()

    def test_toggle_collapses_and_expands(self):
        self.assertFalse(getattr(self.window, "_sidebar_collapsed", False))
        self.window._toggle_sidebar_collapsed()
        self.assertTrue(self.window._sidebar_collapsed)
        self.assertEqual(self.window._sidebar_widget.minimumWidth(), theme.SIDEBAR_COLLAPSED_WIDTH)
        self.window._toggle_sidebar_collapsed()
        self.assertFalse(self.window._sidebar_collapsed)

    def test_collapsed_state_persists_across_theme_change(self):
        self.window._toggle_sidebar_collapsed()
        _app.processEvents()
        self.window._on_theme_changed()
        _app.processEvents()
        self.assertTrue(self.window._sidebar_collapsed)
        self.assertEqual(self.window._sidebar_widget.minimumWidth(), theme.SIDEBAR_COLLAPSED_WIDTH)

    def test_collapsed_state_persists_across_view_mode_change(self):
        self.window._toggle_sidebar_collapsed()
        self.window._set_view_mode("summary")
        _app.processEvents()
        self.assertTrue(self.window._sidebar_collapsed)


class AddBranchDialogTest(unittest.TestCase):
    def setUp(self):
        config.set_branches({"본사": []})
        self.window = _fake_dialog_parent()

    def tearDown(self):
        _dispose(self.window)
        _app.processEvents()

    def test_empty_name_rejected_with_inline_error(self):
        dlg = gui.AddBranchDialog(self.window, config.get_branches().keys())
        dlg.show()
        _app.processEvents()
        dlg._name_edit.setText("   ")
        dlg._on_confirm()
        self.assertTrue(dlg._error_banner.isVisible())
        self.assertNotEqual(dlg.result(), QDialog.DialogCode.Accepted)
        self.assertIsNone(dlg.result_name)
        _dispose(dlg)

    def test_duplicate_name_rejected_with_inline_error(self):
        dlg = gui.AddBranchDialog(self.window, config.get_branches().keys())
        dlg.show()
        _app.processEvents()
        dlg._name_edit.setText("본사")
        dlg._on_confirm()
        self.assertTrue(dlg._error_banner.isVisible())
        self.assertNotEqual(dlg.result(), QDialog.DialogCode.Accepted)
        _dispose(dlg)

    def test_valid_name_accepts(self):
        dlg = gui.AddBranchDialog(self.window, config.get_branches().keys())
        dlg._name_edit.setText("지사2")
        dlg._on_confirm()
        self.assertEqual(dlg.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dlg.result_name, "지사2")


class BranchManagerMultiMatchTest(unittest.TestCase):
    """Section 14: 검색어와 일치하는 즐겨찾기가 여러 개면 첫 번째를 임의로
    골라 추가하지 않고, 후보 목록에서 사용자가 직접 선택해야 한다."""

    def setUp(self):
        config.set_branches({"본사": []})
        config.set_favorites(["충청북도 진천군", "충청북도 청주시", "경기도 안성시"])
        self.window = _fake_dialog_parent()
        self.dlg = gui.BranchManagerDialog(self.window, lambda: None)
        self.dlg.show()
        _app.processEvents()

    def tearDown(self):
        _dispose(self.dlg)
        _dispose(self.window)
        _app.processEvents()

    def test_multiple_matches_shows_candidates_without_auto_adding(self):
        search_edit = self.dlg.findChild(LineEdit)
        search_edit.setText("충청북도")
        self.dlg._add_region_from_search("본사", search_edit)
        _app.processEvents()

        self.assertTrue(self.dlg._region_search_candidates.isVisible())
        self.assertEqual(self.dlg._region_search_candidates.count(), 2)
        self.assertEqual(config.get_branches()["본사"], [])

    def test_selecting_a_candidate_adds_only_that_one(self):
        search_edit = self.dlg.findChild(LineEdit)
        search_edit.setText("충청북도")
        self.dlg._add_region_from_search("본사", search_edit)
        _app.processEvents()

        item = self.dlg._region_search_candidates.item(0)
        expected_region = item.data(Qt.ItemDataRole.UserRole)[1]
        self.dlg._on_region_candidate_selected(item)
        _app.processEvents()

        self.assertEqual(config.get_branches()["본사"], [expected_region])

    def test_single_match_adds_directly(self):
        search_edit = self.dlg.findChild(LineEdit)
        search_edit.setText("안성")
        self.dlg._add_region_from_search("본사", search_edit)
        _app.processEvents()

        self.assertFalse(self.dlg._region_search_candidates.isVisible())
        self.assertEqual(config.get_branches()["본사"], ["경기도 안성시"])

    def test_no_match_shows_warning_without_adding(self):
        search_edit = self.dlg.findChild(LineEdit)
        search_edit.setText("존재하지않는지역명")
        self.dlg._add_region_from_search("본사", search_edit)
        _app.processEvents()

        self.assertTrue(self.dlg._region_search_banner.isVisible())
        self.assertFalse(self.dlg._region_search_candidates.isVisible())
        self.assertEqual(config.get_branches()["본사"], [])


class SignalDuplicationTest(unittest.TestCase):
    """Section 5/13: 새로 추가한 키보드 활성화 경로(activated)가 기존
    마우스 경로(doubleClicked/cellClicked)와 겹쳐 같은 동작을 두 번
    호출하지 않는지 확인한다."""

    def setUp(self):
        config.set_favorites(["충청북도 진천군"])
        self.window = _new_window()
        self.window.reports = {"충청북도 진천군": _report("충청북도 진천군")}
        self.window.selected_region = "충청북도 진천군"
        self.window._refresh_current_view()
        self.window.show()
        _app.processEvents()

    def tearDown(self):
        _dispose(self.window)
        _app.processEvents()

    def test_forecast_row_double_click_and_activated_are_separate_user_actions(self):
        """더블클릭 한 번 = doubleClicked 1회만, Enter 한 번 = activated
        1회만 - 서로 다른 조작이 서로를 유발해 같은 동작이 두 번 나가면 안 된다."""
        calls = []
        self.window._open_hourly_detail = lambda n, d: calls.append((n, d))
        self.window._render_forecast(self.window.selected_region, self.window.reports["충청북도 진천군"]["forecast"])
        _app.processEvents()

        rows = [
            self.window.forecast_layout.itemAt(i).widget()
            for i in range(self.window.forecast_layout.count())
            if self.window.forecast_layout.itemAt(i).widget().__class__.__name__ == "ForecastRow"
        ]
        row = rows[0]

        row.doubleClicked.emit()
        self.assertEqual(len(calls), 1)

        row.activated.emit()
        self.assertEqual(len(calls), 2)  # 더블클릭 1번 + Enter 1번 = 서로 다른 두 번의 사용자 조작

    def test_summary_cell_enter_key_reuses_click_handler_without_double_open(self):
        config.set_branches({"본사": ["충청북도 진천군"]})
        self.window._set_view_mode("summary")
        _app.processEvents()

        calls = []
        self.window._open_branch_range = lambda name, members: calls.append((name, members))

        table = self.window.summary_table
        table.setCurrentCell(0, 0)
        _app.processEvents()
        ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(table, ev)
        _app.processEvents()

        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
