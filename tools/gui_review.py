"""weather_duty GUI 리뷰 도구.

목(mock) 데이터로 미리 정한 21개 화면 시나리오를 창 크기 3종(narrow/default/
wide) x 테마 2종(light/dark) 조합으로 렌더링해 artifacts/gui_review/ 아래에
스크린샷(PNG)으로 저장한다. 실제 기상청 API를 호출하지 않고, 실제 사용자
설정 파일(~/.weather_duty/config.json)도 절대 건드리지 않는다 - config 모듈의
저장 위치를 이 프로세스 안에서만 임시 디렉터리로 바꿔치기한 뒤 그 안에서만
즐겨찾기/지사/서비스키를 채운다(원본 config.py는 수정하지 않음).

사용법:
    QT_QPA_PLATFORM=offscreen python tools/gui_review.py
    (일부 환경은 QT_QPA_PLATFORM 없이도 오프스크린으로 동작하지만, CI/서버
    환경처럼 디스플레이가 없으면 위 환경변수가 필요하다.)

각 시나리오는 스크린샷 대상 위젯(QMainWindow 또는 QDialog)을 만들어 돌려주는
함수 하나로 정의되어 있고, 이 파일 아래쪽 SCENARIOS 리스트에 이름과 함께
등록되어 있다. 새 시나리오를 추가하려면 함수 하나 만들고 리스트에 추가하면 된다.
"""
import os
import shutil
import sys
import tempfile

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from weather_duty import config  # noqa: E402

# 실제 ~/.weather_duty/config.json을 절대 읽거나 쓰지 않도록, 이 프로세스
# 안에서만 config 모듈이 보는 저장 위치를 임시 디렉터리로 바꾼다. config.py
# 자체는 그대로 두고(모든 함수가 매 호출 시 이 두 전역을 다시 읽으므로) 여기서
# 값만 덮어써도 안전하다.
_TMP_CONFIG_DIR = tempfile.mkdtemp(prefix="weather_duty_gui_review_config_")
config.CONFIG_DIR = _TMP_CONFIG_DIR
config.CONFIG_PATH = os.path.join(_TMP_CONFIG_DIR, "config.json")
# WeatherDutyApp.__init__()이 매번 config.seed_default_branches_if_needed()를
# 부르는데, 그 함수는 "branches" 키가 원본 파일에 한 번도 저장된 적 없으면
# DEFAULT_BRANCHES(실제 관할 구성, ~20개 지역명)를 즐겨찾기에 병합해 버린다.
# 이 임시 config는 매 시나리오마다 새로 만드는 WeatherDutyApp()에서 반복
# 트리거되므로, 미리 빈 branches를 한 번 저장해 두어 시딩 자체가 절대 일어나지
# 않게 막는다(그래야 각 시나리오가 지정한 즐겨찾기만 그대로 유지된다).
config.set_branches({})
# 즐겨찾기 종합보기는 config.get_service_key()가 비어 있으면 실제 데이터
# 유무와 무관하게 무조건 "서비스키 설정이 필요합니다" 빈 상태로 빠진다 -
# 이 임시 config는 서비스키가 절대 채워질 일이 없으므로, 실제 키처럼 보이되
# 진짜 API 호출에는 전혀 쓰이지 않는(모든 시나리오가 window.reports를 직접
# 채우고 refresh_all()은 막아 둠) 가짜 문자열을 하나 저장해 둔다.
config.set_service_key("MOCK-REVIEW-KEY-NOT-A-REAL-KEY")

from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from weather_duty import gui, theme  # noqa: E402

ARTIFACTS_DIR = os.path.join(_REPO_ROOT, "artifacts", "gui_review")
SIZES = [("narrow", 960, 600), ("default", 1180, 700), ("wide", 1440, 900)]
THEMES = ["light", "dark"]


def _hourly(base_temp=20):
    return [
        {
            "time": f"{h:02d}00", "temp": str(base_temp + h % 5), "feels_like": base_temp - 1 + h % 4,
            "pop": 30 if h in (9, 12) else 10, "pcp": "1.0mm" if h == 9 else "강수없음",
            "condition": "구름많음",
        }
        for h in range(0, 24, 3)
    ]


def _report(name, tmin, tmax, pcp, feels_min, feels_max, source="단기예보",
            warn=None, hourly=True, errors=None):
    hourly_data = _hourly(tmin) if hourly else []
    return {
        "name": name,
        "current": {"temp": str(tmax - 2), "rain_1h": "0", "obs_time": "2026-08-29 09:00"},
        "forecast": [
            {"date": "20260828", "tmin": str(tmin - 1), "tmax": str(tmax - 1), "pop": 20,
             "pcp": "강수없음", "condition": "맑음", "source": "실측",
             "feels_like_min": feels_min - 1, "feels_like_max": feels_max - 1, "hourly": hourly_data},
            {"date": "20260829", "tmin": str(tmin), "tmax": str(tmax), "pop": 60, "pcp": pcp,
             "condition": "구름많음", "source": source,
             "feels_like_min": feels_min, "feels_like_max": feels_max, "hourly": hourly_data},
            {"date": "20260905", "tmin": str(tmin - 3), "tmax": str(tmax - 2), "pop": 40, "pcp": "",
             "condition": "흐림", "source": "중기예보", "feels_like_min": None, "feels_like_max": None,
             "hourly": []},
        ],
        "warnings": [warn] if warn else [],
        "errors": errors or [],
    }


def _new_window():
    """즐겨찾기/지사/서비스키를 비운 새 WeatherDutyApp - 시작 시 자동 조회
    타이머(refresh_all)가 실제 네트워크를 두드리지 않도록 바로 무력화한다."""
    window = gui.WeatherDutyApp()
    window.refresh_all = lambda: None
    return window


def _settle(app, times=3):
    for _ in range(times):
        app.processEvents()


# ---------------------------------------------------------------------------
# 시나리오 (지역별 상세) - 9개
# ---------------------------------------------------------------------------

def scenario_detail_normal(app):
    config.set_favorites(["충청북도 진천군", "경기도 안성시"])
    window = _new_window()
    window.reports = {
        "충청북도 진천군": _report("충청북도 진천군", 24, 33, "12mm", 26.5, 35.2),
        "경기도 안성시": _report("경기도 안성시", 23, 31, "3mm", 25.1, 32.0),
    }
    window.selected_region = "충청북도 진천군"
    window._refresh_current_view()
    return window


def scenario_detail_warning_active(app):
    config.set_favorites(["충청북도 진천군"])
    window = _new_window()
    window.reports = {
        "충청북도 진천군": _report("충청북도 진천군", 24, 33, "12mm", 26.5, 35.2, warn="폭염경보 충청북도 발효"),
    }
    window.selected_region = "충청북도 진천군"
    window._refresh_current_view()
    return window


def scenario_detail_partial_error(app):
    config.set_favorites(["충청북도 진천군"])
    window = _new_window()
    window.reports = {
        "충청북도 진천군": _report(
            "충청북도 진천군", 24, 33, "12mm", 26.5, 35.2,
            errors=["특보 조회 실패: 응답 시간 초과"],
        ),
    }
    window.selected_region = "충청북도 진천군"
    window._refresh_current_view()
    return window


def scenario_detail_empty_forecast(app):
    config.set_favorites(["충청북도 진천군"])
    window = _new_window()
    report = _report("충청북도 진천군", 24, 33, "12mm", 26.5, 35.2)
    report["forecast"] = []
    window.reports = {"충청북도 진천군": report}
    window.selected_region = "충청북도 진천군"
    window._refresh_current_view()
    return window


def scenario_detail_long_region_name(app):
    long_name = "충청북도 청주시 흥덕구 (매우 긴 사용자 정의 지역명 테스트)"
    config.set_favorites([long_name])
    window = _new_window()
    window.reports = {long_name: _report(long_name, 24, 33, "12mm", 26.5, 35.2)}
    window.selected_region = long_name
    window._refresh_current_view()
    return window


def scenario_detail_service_key_missing(app):
    config.set_favorites(["충청북도 진천군"])
    window = _new_window()
    window.selected_region = "충청북도 진천군"
    window._render_favorite_list(config.get_favorites())
    window._render_forecast_service_key_missing()
    return window


def scenario_detail_loading(app):
    config.set_favorites(["충청북도 진천군"])
    window = _new_window()
    window.selected_region = "충청북도 진천군"
    window._render_favorite_list(config.get_favorites())
    window._render_forecast_loading("충청북도 진천군")
    return window


def scenario_detail_no_favorites(app):
    config.set_favorites([])
    window = _new_window()
    window._refresh_current_view()
    return window


def scenario_detail_forecast_row_no_hourly(app):
    """중기예보(시간별 데이터 없음) 행의 상세보기 버튼 비활성 상태 확인용 -
    scenario_detail_normal과 같은 데이터라도 세 번째 행(중기예보)이 항상 있다."""
    return scenario_detail_normal(app)


# ---------------------------------------------------------------------------
# 시나리오 (즐겨찾기 종합) - 5개
# ---------------------------------------------------------------------------

def scenario_summary_normal(app):
    config.set_favorites(["충청북도 진천군", "경기도 안성시", "경상북도 상주시"])
    config.set_branches({"본사": ["충청북도 진천군", "경기도 안성시"], "남부지사": ["경상북도 상주시"]})
    window = _new_window()
    window.reports = {
        "충청북도 진천군": _report("충청북도 진천군", 24, 33, "12mm", 26.5, 35.2, warn="폭염경보 충청북도 발효"),
        "경기도 안성시": _report("경기도 안성시", 23, 31, "3mm", 25.1, 32.0),
        "경상북도 상주시": _report("경상북도 상주시", 22, 30, "강수없음", 24.0, 30.5),
    }
    window._set_view_mode("summary")
    return window


def scenario_summary_partial_error(app):
    config.set_favorites(["충청북도 진천군", "경기도 안성시"])
    config.set_branches({"본사": ["충청북도 진천군", "경기도 안성시"]})
    window = _new_window()
    window.reports = {
        "충청북도 진천군": _report("충청북도 진천군", 24, 33, "12mm", 26.5, 35.2),
        "경기도 안성시": _report(
            "경기도 안성시", 23, 31, "3mm", 25.1, 32.0, errors=["데이터 조회 실패: 응답 시간 초과"],
        ),
    }
    window._set_view_mode("summary")
    return window


def scenario_summary_all_error(app):
    config.set_favorites(["충청북도 진천군"])
    config.set_branches({"본사": ["충청북도 진천군"]})
    window = _new_window()
    window.reports = {
        "충청북도 진천군": _report(
            "충청북도 진천군", 24, 33, "12mm", 26.5, 35.2, errors=["데이터 조회 실패: 응답 시간 초과"],
        ),
    }
    window._set_view_mode("summary")
    return window


def scenario_summary_no_favorites(app):
    config.set_favorites([])
    config.set_branches({})
    window = _new_window()
    window._set_view_mode("summary")
    return window


def scenario_summary_no_branches(app):
    config.set_favorites(["충청북도 진천군"])
    config.set_branches({})
    window = _new_window()
    window.reports = {"충청북도 진천군": _report("충청북도 진천군", 24, 33, "12mm", 26.5, 35.2)}
    window._set_view_mode("summary")
    return window


# ---------------------------------------------------------------------------
# 시나리오 (사이드바/포커스) - 2개
# ---------------------------------------------------------------------------

def scenario_sidebar_collapsed(app):
    window = scenario_detail_normal(app)
    window._toggle_sidebar_collapsed()
    return window


def scenario_detail_forecast_row_focus(app):
    window = scenario_detail_normal(app)
    _settle(app)
    rows = [
        window.forecast_layout.itemAt(i).widget()
        for i in range(window.forecast_layout.count())
        if window.forecast_layout.itemAt(i).widget().__class__.__name__ == "ForecastRow"
    ]
    if rows:
        rows[0].setFocus()
    return window


# ---------------------------------------------------------------------------
# 시나리오 (다이얼로그) - 5개
# ---------------------------------------------------------------------------

def scenario_add_branch_dialog_error(app):
    config.set_branches({"본사": []})
    window = _new_window()
    dlg = gui.AddBranchDialog(window, config.get_branches().keys())
    dlg._name_edit.setText("본사")
    dlg._on_confirm()
    dlg._extra_window = window  # 창이 GC로 먼저 닫히지 않게 붙잡아 둠
    return dlg


def scenario_branch_manager_multi_match(app):
    config.set_branches({"본사": []})
    config.set_favorites(["충청북도 진천군", "충청북도 청주시", "경기도 안성시"])
    window = _new_window()
    dlg = gui.BranchManagerDialog(window, lambda: None)
    dlg._extra_window = window
    _settle(app)
    from qfluentwidgets import LineEdit
    search_edit = dlg.findChild(LineEdit)
    search_edit.setText("충청북도")
    dlg._add_region_from_search("본사", search_edit)
    return dlg


def scenario_region_manager_dialog(app):
    config.set_favorites(["충청북도 진천군", "경기도 안성시"])
    window = _new_window()
    dlg = gui.RegionManagerDialog(window, lambda **kw: None)
    dlg._extra_window = window
    return dlg


def scenario_hourly_detail_dialog(app):
    config.set_favorites(["충청북도 진천군"])
    window = _new_window()
    day = _report("충청북도 진천군", 24, 33, "12mm", 26.5, 35.2)["forecast"][1]
    dlg = gui.HourlyDetailDialog(window, "충청북도 진천군", day)
    dlg._extra_window = window
    return dlg


def scenario_settings_dialog(app):
    window = _new_window()
    dlg = gui.SettingsDialog(window, lambda: None)
    dlg._extra_window = window
    return dlg


# ---------------------------------------------------------------------------

SCENARIOS = [
    ("detail_normal", scenario_detail_normal),
    ("detail_warning_active", scenario_detail_warning_active),
    ("detail_partial_error", scenario_detail_partial_error),
    ("detail_empty_forecast", scenario_detail_empty_forecast),
    ("detail_long_region_name", scenario_detail_long_region_name),
    ("detail_service_key_missing", scenario_detail_service_key_missing),
    ("detail_loading", scenario_detail_loading),
    ("detail_no_favorites", scenario_detail_no_favorites),
    ("detail_forecast_row_no_hourly", scenario_detail_forecast_row_no_hourly),
    ("summary_normal", scenario_summary_normal),
    ("summary_partial_error", scenario_summary_partial_error),
    ("summary_all_error", scenario_summary_all_error),
    ("summary_no_favorites", scenario_summary_no_favorites),
    ("summary_no_branches", scenario_summary_no_branches),
    ("sidebar_collapsed", scenario_sidebar_collapsed),
    ("detail_forecast_row_focus", scenario_detail_forecast_row_focus),
    ("add_branch_dialog_error", scenario_add_branch_dialog_error),
    ("branch_manager_multi_match", scenario_branch_manager_multi_match),
    ("region_manager_dialog", scenario_region_manager_dialog),
    ("hourly_detail_dialog", scenario_hourly_detail_dialog),
    ("settings_dialog", scenario_settings_dialog),
]

assert len(SCENARIOS) == 21, f"시나리오는 21개여야 한다(현재 {len(SCENARIOS)}개)"


def _set_theme(theme_name):
    from qfluentwidgets import Theme, setTheme
    setTheme(Theme.DARK if theme_name == "dark" else Theme.LIGHT)


def run():
    if os.path.isdir(ARTIFACTS_DIR):
        shutil.rmtree(ARTIFACTS_DIR)
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)

    app = QApplication.instance() or QApplication([])
    theme.init_app_theme()
    theme.load_bundled_fonts()
    app.setFont(theme.font(13, QFont.Weight.Normal))

    total = 0
    for theme_name in THEMES:
        _set_theme(theme_name)
        for size_name, w, h in SIZES:
            out_dir = os.path.join(ARTIFACTS_DIR, theme_name, size_name)
            os.makedirs(out_dir, exist_ok=True)
            for scenario_name, builder in SCENARIOS:
                widget = builder(app)
                widget.resize(w, h)
                widget.show()
                _settle(app)
                path = os.path.join(out_dir, f"{scenario_name}.png")
                widget.grab().save(path)
                widget.close()
                _settle(app)
                total += 1
                print(f"[{theme_name}/{size_name}] {scenario_name} -> {path}")

    shutil.rmtree(_TMP_CONFIG_DIR, ignore_errors=True)
    print(f"\n총 {total}개 스크린샷 생성 완료 ({len(SCENARIOS)}개 시나리오 x {len(SIZES)}개 크기 x {len(THEMES)}개 테마).")
    print(f"저장 위치: {ARTIFACTS_DIR}")


if __name__ == "__main__":
    run()
