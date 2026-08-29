"""폭염/풍수해/제설 근무용 날씨 모니터 - PySide6 + PySide6-Fluent-Widgets(qfluentwidgets) GUI.

서버 없이 단일 실행 파일(개별 프로그램)로 동작하며, 기상청 API를 직접 호출한다.
디자인은 theme.py의 "Calm Operations Dashboard" 토큰 체계(색상/타이포그래피/
spacing/radius)를 따르는 절제된 톤이고, 위젯 자체는 PyQt-Fluent-Widgets
(https://github.com/zhiyiYo/PyQt-Fluent-Widgets)의 세그먼트 컨트롤/토스트
알림 등을 그대로 가져다 쓴다.
"""
import datetime
import re
import threading

from PySide6.QtCore import Qt, QObject, QPointF, QRectF, QSize, QTimer, Signal
from PySide6.QtGui import QFont, QFontMetrics, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QFrame, QGridLayout, QHeaderView, QLabel, QSizePolicy,
    QVBoxLayout, QHBoxLayout, QDialog, QSplitter, QStackedWidget,
    QTableWidgetItem, QAbstractItemView, QListWidgetItem,
)

from qfluentwidgets import (
    PushButton, PrimaryPushButton,
    LineEdit, SearchLineEdit, ComboBox, CheckBox, TableWidget, ListWidget,
    ScrollArea, SingleDirectionScrollArea, SegmentedWidget, InfoBar, InfoBarPosition,
    FluentIcon, SystemThemeListener,
)

from . import config, kma_client, regions, theme
from . import ui_components as uic

_PCP_NUMBER_RE = re.compile(r"([\d.]+)")


def _pcp_numeric(pcp_str):
    """요약 화면에서 지사 내 최다 강수 지역을 고르기 위한 정렬용 숫자값."""
    if not pcp_str or pcp_str == "강수없음":
        return 0.0
    match = _PCP_NUMBER_RE.search(pcp_str)
    return float(match.group(1)) if match else 0.0


def _pcp_peak_hour_text(day):
    """시간별 데이터 중 강수량이 가장 많은 시각을 "(14시 최대)" 형태로 반환.
    강수가 없거나(전부 0) 시간별 데이터가 없으면 빈 문자열."""
    hourly = (day or {}).get("hourly") or []
    best_time, best_amount = None, 0.0
    for h in hourly:
        amount = _pcp_numeric(h.get("pcp"))
        if amount > best_amount:
            best_amount = amount
            best_time = h.get("time")
    if not best_time:
        return ""
    return f"({_format_fcst_time(best_time)} 최대)"


def _pcp_display_text(day):
    """강수량 칸에 보여줄 문구.
    - 단기예보(강수량 데이터 있음): "3mm" 같은 실제 값 또는 "강수없음"
    - 중기예보(원래 강수량 없이 확률만 제공): 출처 배지가 이미 "중기예보"를
      보여주므로 값 칸에서는 반복하지 않고 "—"만 쓴다(이유는 tooltip으로 -
      _pcp_display_tooltip() 참고)
    - 데이터 자체가 없음(조회 중/실패): "-" """
    if day is None:
        return "-"
    pcp = day.get("pcp")
    if pcp:
        return pcp
    if day.get("source") == "중기예보":
        return "—"
    return "강수없음" if day.get("pop") is not None else "-"


def _pcp_display_tooltip(day):
    """_pcp_display_text()가 "—"로 줄인 경우에만 이유를 보완하는 tooltip."""
    if day is not None and day.get("source") == "중기예보" and not day.get("pcp"):
        return "중기예보는 강수량을 제공하지 않습니다."
    return ""


def _format_fcst_time(time_str):
    if time_str and len(time_str) >= 2:
        return f"{time_str[:2]}시"
    return time_str or "-"


def _format_min_max(min_value, max_value, unit="°"):
    """최저/최고 계열 값을 "23°/31°" 형태로 표시만 만든다 - 0은 유효한
    값이라 truthy 검사(`if tmin or tmax`)를 쓰면 "0°"가 "-"로 사라지는
    버그가 있었다. 값 자체는 그대로 두고 표시 문자열만 만든다."""
    if min_value is None and max_value is None:
        return "—"
    left = f"{min_value}{unit}" if min_value is not None else "—"
    right = f"{max_value}{unit}" if max_value is not None else "—"
    return f"{left} / {right}"


_WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


def _pretty_date_with_weekday(date_str, today_str=None):
    """YYYYMMDD 날짜 값을 "오늘 · 08/28 (금)" / "08/29 (토)" 형태로 표시만
    바꾼다 - 날짜 값 자체(day["date"])는 건드리지 않고 UI에서만 요일을 계산."""
    if not date_str or len(date_str) != 8:
        return date_str or "-"
    try:
        d = datetime.date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
    except ValueError:
        return f"{date_str[4:6]}/{date_str[6:8]}"
    pretty = f"{date_str[4:6]}/{date_str[6:8]} ({_WEEKDAY_KO[d.weekday()]})"
    return f"오늘 · {pretty}" if today_str and date_str == today_str else pretty


def _pop_tone(pop):
    """강수확률 배지 톤. 강수확률은 오류도 실제 기상특보도 아니므로
    danger/warning을 쓰지 않는다(그 톤은 데이터 조회 실패·실제 특보 전용) -
    theme.pop_color()와 같은 기준(30/70)으로 neutral/info/accent만 쓴다."""
    if pop is None:
        return "neutral"
    if pop >= 70:
        return "accent"
    if pop >= 30:
        return "info"
    return "neutral"


def _forecast_row_tooltip(day):
    """실제 시간별 데이터가 있는 행에서만 "시간별"이라고 명시한다 - 중기예보처럼
    시간별 데이터가 없는 행에 오해를 주는 문구를 달지 않기 위함."""
    if day.get("hourly"):
        return "더블클릭하여 시간별 상세보기"
    return "더블클릭하여 상세 정보 보기"


def _hourly_detail_reason(day):
    """시간별(hourly) 데이터가 없는 이유를 한 곳에서만 판단한다 - ForecastRow의
    상세보기 버튼 tooltip과 HourlyDetailDialog의 안내 문구가 서로 다른 말을
    하지 않도록 같은 로직을 공유한다."""
    if day.get("source") == "중기예보":
        return "중기예보(4일 이후)는 시간별 데이터를 제공하지 않습니다."
    if day.get("source") == "실측":
        return "이 날짜의 시간별 실측 자료를 불러오지 못했습니다."
    return "시간별 데이터가 없습니다."


def _summary_date_chip_text(date_str, today_str=None):
    """종합보기 날짜 칩에 쓸 짧은 표시 문구만 만든다 - routeKey/date_str 값
    자체(선택 상태 판정, _on_summary_date_selected에 넘기는 값)는 그대로 둔다.
    "오늘 08/28" / "어제 08/27" / "08/29 토" 형태."""
    if not date_str or len(date_str) != 8:
        return date_str or "-"
    try:
        d = datetime.date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
    except ValueError:
        return f"{date_str[4:6]}/{date_str[6:8]}"
    mmdd = f"{date_str[4:6]}/{date_str[6:8]}"
    if today_str:
        if date_str == today_str:
            return f"오늘 {mmdd}"
        try:
            today_d = datetime.date(int(today_str[:4]), int(today_str[4:6]), int(today_str[6:8]))
            if (today_d - d).days == 1:
                return f"어제 {mmdd}"
        except ValueError:
            pass
    return f"{mmdd} {_WEEKDAY_KO[d.weekday()]}"


def toast(parent, kind, title, content):
    """즉시 사라지는 토스트 알림(성공/오류 확인용). 저장/추가 같은 짧은 확인
    메시지에 쓰고, 사용자가 반드시 읽고 넘어가야 하는 입력 검증 오류는
    각 다이얼로그 안의 InlineBanner로 보여준다(기본 Qt 팝업을 쓰지 않는다)."""
    method = getattr(InfoBar, kind)
    method(
        title=title, content=content, orient=Qt.Orientation.Horizontal,
        isClosable=True, duration=2500, position=InfoBarPosition.TOP,
        parent=parent,
    )


def _dot_icon(color_hex, diameter=8):
    """즐겨찾기 목록에서 "조회 중" 표시용 작은 점 아이콘. 항목의 텍스트나
    UserRole은 그대로 두고, 아이콘 하나로만 진행 상태를 곁들인다(반복 애니메이션 없음)."""
    pixmap = QPixmap(diameter, diameter)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_qcolor(color_hex))
    painter.drawEllipse(0, 0, diameter, diameter)
    painter.end()
    return QIcon(pixmap)


def _build_app_icon():
    """앱 창/작업표시줄 아이콘. 외부 이미지 파일이나 새 패키지 없이,
    accent 색 둥근 사각형 배경 위에 간단한 흰색 해+구름 도형만 QPainter로
    그린 벡터 아이콘이다(ui_components._draw_weather_icon_pixmap과 같은
    방식) - 여러 크기를 미리 그려 QIcon에 등록해 두면 OS가 배율에 맞는
    걸 알아서 골라 쓰므로 고배율(레티나/DPI 150%)에서도 흐려지지 않는다.
    라이트/다크 테마와 무관하게(작업표시줄 아이콘은 테마 전환에 반응할
    필요가 없다) LIGHT 팔레트의 accent 색으로 고정한다."""
    icon = QIcon()
    accent = _qcolor(theme.LIGHT["accent"])
    white = _qcolor("#FFFFFF")
    for size in (16, 24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        painter.setBrush(accent)
        radius = size * 0.22
        painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)

        painter.setBrush(white)
        sun_r = size * 0.15
        painter.drawEllipse(QPointF(size * 0.38, size * 0.40), sun_r, sun_r)

        cloud_h = size * 0.22
        cloud_rect = QRectF(size * 0.28, size * 0.54, size * 0.58, cloud_h)
        painter.drawRoundedRect(cloud_rect, cloud_h / 2, cloud_h / 2)
        painter.drawEllipse(QPointF(size * 0.42, size * 0.54), cloud_h * 0.5, cloud_h * 0.5)
        painter.drawEllipse(QPointF(size * 0.60, size * 0.50), cloud_h * 0.58, cloud_h * 0.58)

        painter.end()
        icon.addPixmap(pixmap)
    return icon


_STATUS_PILL_LABELS = ["대기", "조회 중", "갱신 완료", "일부 오류", "서비스키 필요"]


def _status_pill_min_width():
    """상태 pill 텍스트가 "조회 중" <-> "서비스키 필요"처럼 바뀔 때 헤더 폭이
    흔들리지 않도록, 나올 수 있는 문구 중 가장 넓은 것 기준으로 최소 너비를 잡는다."""
    metrics = QFontMetrics(theme.font_role("micro"))
    widest = max(metrics.horizontalAdvance(label) for label in _STATUS_PILL_LABELS)
    return widest + theme.SPACE_3 * 2 + theme.SPACE_3


def _bring_to_front(win):
    win.raise_()
    win.activateWindow()


def _clear_layout(layout):
    """레이아웃의 자식 위젯을 전부 제거한다. deleteLater()만 하면 실제 삭제가
    다음 이벤트 루프까지 미뤄져 새로 그린 위젯과 잠깐 겹쳐 보이므로, setParent(None)로
    화면에서 즉시 떼어낸 뒤 삭제를 예약한다.

    addLayout()으로 넣은 중첩 레이아웃(예: 한 줄짜리 QHBoxLayout)은
    item.widget()이 None을 반환해 예전엔 그냥 건너뛰었는데, 그 안의
    위젯들은 여전히 부모(다이얼로그)에 매달린 채 화면에서만 안 보일 뿐
    실제로는 지워지지 않고 남아 있었다 - _render_right_panel()처럼 같은
    다이얼로그를 열어 둔 채로 여러 번 다시 그리는 화면에서, 이전 줄의
    위젯이 새로 그린 위젯 위에 그대로 겹쳐 보이는 버그로 실측됨. 중첩
    레이아웃도 재귀적으로 비워야 한다."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
            continue
        sub_layout = item.layout()
        if sub_layout is not None:
            _clear_layout(sub_layout)


# ---------------------------------------------------------------------------
# 다이얼로그
# ---------------------------------------------------------------------------


class _ThemedDialog(QDialog):
    """모든 다이얼로그가 공유하는 배경색 처리. 다이얼로그를 열어 둔 채로
    라이트/다크를 전환하면(_bind_background()를 호출한 경우) 배경이 계속
    현재 테마를 따라가고, 그러지 않았더라도 새로 여는 다이얼로그는 항상 그
    시점의 theme.colors()로 배경을 칠하므로 이전 테마 색이 인라인 스타일에
    남지 않는다. 다이얼로그 내부에서 개별적으로 그리는 표/배지 등은 대부분
    ui_components.py 위젯(자체적으로 bind_theme_change를 건다)을 쓰므로 함께
    갱신되고, 직접 그린 QTableWidgetItem 색상처럼 일부만 남을 수 있다."""

    def _bind_background(self):
        self._extra_theme_refresh = []
        self._refresh_background()
        theme.bind_theme_change(self, self._refresh_background)

    def _on_theme_refresh(self, callback):
        """다이얼로그가 열려 있는 동안 테마가 바뀌면 배경과 함께 다시 그릴
        콜백을 등록한다 - 직접 그린 QFrame 패널/표 헤더 인라인 스타일처럼
        ui_components 위젯이 아니라서 자동으로 갱신되지 않는 것들을 위한 것."""
        self._extra_theme_refresh.append(callback)

    def _refresh_background(self):
        c = theme.colors()
        self.setStyleSheet(f"QDialog {{ background-color:{c['background']}; border:none; }}")
        for callback in getattr(self, "_extra_theme_refresh", []):
            callback()


class HourlyDetailDialog(_ThemedDialog):
    """일자별 예보 칸(지역별 상세/종합보기 어느 쪽이든)을 더블클릭하면 그 날의
    3시간 구간별 날씨/기온/체감온도/강수량/강수확률을 시간이 행(row)인 표로
    보여준다. 데이터 순서·값은 원래 hourly 리스트 그대로이고, 메인 화면
    표(TABLE_HEADER_HEIGHT/TABLE_ROW_HEIGHT)와 같은 행 높이 토큰을 쓴다."""

    def __init__(self, parent, region_name, day):
        super().__init__(parent)
        pretty_date = day.get("date", "")
        if len(pretty_date) == 8:
            pretty_date = f"{pretty_date[:4]}-{pretty_date[4:6]}-{pretty_date[6:8]}"
        self.setWindowTitle(f"{region_name} {pretty_date} 시간별 예보")
        self._bind_background()
        self.setMinimumWidth(600)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            theme.DIALOG_CONTENT_MARGIN, theme.DIALOG_CONTENT_MARGIN,
            theme.DIALOG_CONTENT_MARGIN, theme.DIALOG_CONTENT_MARGIN,
        )
        outer.setSpacing(theme.SPACE_4)

        outer.addWidget(uic.DialogHeader(region_name, f"{pretty_date} 시간별 예보", self))

        hourly = day.get("hourly") or []

        # ---------- 요약 정보(00~24시 누적/기온/체감) - surface_alt 그룹 하나로 ----------
        summary_bits = [("00~24시 누적 강수량", _pcp_display_text(day))]
        if day.get("tmin") is not None or day.get("tmax") is not None:
            summary_bits.append(("기온", _format_min_max(day.get("tmin"), day.get("tmax"))))
        if day.get("feels_like_min") is not None:
            summary_bits.append(("체감", _format_min_max(day.get("feels_like_min"), day.get("feels_like_max"))))
        summary_frame = QFrame(self)
        summary_frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        def _restyle_summary_frame():
            sc = theme.colors()
            summary_frame.setStyleSheet(
                f"QFrame {{ background-color:{sc['surface_alt']}; border:none; border-radius:{theme.RADIUS_PANEL}px; }}"
            )

        _restyle_summary_frame()
        self._on_theme_refresh(_restyle_summary_frame)
        summary_layout = QHBoxLayout(summary_frame)
        summary_layout.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        summary_layout.setSpacing(theme.SPACE_6)
        for label_text, value_text in summary_bits:
            block = uic.MetricBlock(value_text, label_text, summary_frame, value_font_role="card_title")
            summary_layout.addWidget(block)
        summary_layout.addStretch(1)
        outer.addWidget(summary_frame)

        # ---------- 시간대별 표(또는 시간별 데이터가 없는 이유 안내) ----------
        if not hourly:
            reason = _hourly_detail_reason(day)
            empty = uic.EmptyState("시간별 데이터가 없습니다", reason, self)
            empty.setMinimumHeight(160)
            outer.addWidget(empty, 1)
        else:
            table = TableWidget(self)
            table.setColumnCount(6)
            table.setHorizontalHeaderLabels(["시각", "날씨", "기온", "체감온도", "강수량", "강수확률"])
            table.verticalHeader().hide()
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            table.setBorderRadius(theme.RADIUS_CARD)
            table.verticalHeader().setDefaultSectionSize(theme.TABLE_ROW_HEIGHT)
            table.horizontalHeader().setFixedHeight(theme.TABLE_HEADER_HEIGHT)
            table.horizontalHeader().setStretchLastSection(False)
            table.setWordWrap(False)
            table.setTextElideMode(Qt.TextElideMode.ElideRight)
            table.horizontalHeader().setFont(theme.font_role("label"))
            header = table.horizontalHeader()
            for col in range(6):
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
            table.setRowCount(len(hourly))

            def _restyle_table():
                tc = theme.colors()
                table.horizontalHeader().setStyleSheet(
                    f"QHeaderView::section {{ background-color:{tc['surface_alt']}; color:{tc['text_primary']};"
                    f" border:none; padding:0 {theme.SPACE_3}px; }}"
                )
                for row, hour in enumerate(hourly):
                    self._set_hour_cell(
                        table, row, 0, _format_fcst_time(hour.get("time")), tc["text_primary"],
                        theme.font_role("body"), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    )
                    self._set_hour_cell(
                        table, row, 1, hour.get("condition") or "-", tc["text_secondary"],
                        theme.font_role("caption"), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    )
                    temp = hour.get("temp")
                    self._set_hour_cell(
                        table, row, 2, (f"{temp}°" if temp is not None else "-"), tc["text_primary"],
                        theme.font_role("body"), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    )
                    feels_like = hour.get("feels_like")
                    self._set_hour_cell(
                        table, row, 3, (f"{feels_like:.1f}°" if feels_like is not None else "-"),
                        tc["text_primary"], theme.font_role("body"),
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    )
                    self._set_hour_cell(
                        table, row, 4, hour.get("pcp") or "-", tc["text_secondary"],
                        theme.font_role("caption"), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    )
                    pop_val = hour.get("pop")
                    self._set_hour_cell(
                        table, row, 5, (f"{pop_val}%" if pop_val is not None else "-"),
                        theme.pop_color(pop_val, tc), theme.font_role("caption"),
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    )

            _restyle_table()
            self._on_theme_refresh(_restyle_table)
            outer.addWidget(table, 1)

        close_btn = PushButton("닫기", self)
        close_btn.clicked.connect(self.close)
        outer.addWidget(uic.DialogFooter([close_btn], parent=self))

        self.resize(680, 520 if hourly else 320)
        _bring_to_front(self)

    @staticmethod
    def _set_hour_cell(table, row, col, text, color_hex, font, align):
        item = QTableWidgetItem(text)
        item.setForeground(_qcolor(color_hex))
        item.setFont(font)
        item.setTextAlignment(align)
        table.setItem(row, col, item)


def _qcolor(hex_str):
    from PySide6.QtGui import QColor
    return QColor(hex_str)


class RegionManagerDialog(_ThemedDialog):
    """즐겨찾기 추가/삭제 로직(config.set_favorites, on_change 콜백)은 그대로
    두고, 검색 결과 각 행을 "체크박스(추가/삭제) + 이미 즐겨찾기인 행만 보이는
    삭제 아이콘" 구조로 명확히 하고, 빈 상태를 EmptyState로 표준화한다."""

    def __init__(self, parent, on_change):
        super().__init__(parent)
        self.setWindowTitle("즐겨찾기 편집")
        self._bind_background()
        self.setMinimumSize(520, 560)
        self.on_change = on_change
        self.favorites = set(config.get_favorites())
        self.font_body = parent.font_body
        self.font_small = parent.font_small

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            theme.DIALOG_CONTENT_MARGIN, theme.DIALOG_CONTENT_MARGIN,
            theme.DIALOG_CONTENT_MARGIN, theme.DIALOG_CONTENT_MARGIN,
        )
        outer.setSpacing(theme.SPACE_4)

        outer.addWidget(uic.DialogHeader(
            "즐겨찾기 편집", "지역을 검색해 즐겨찾기에 추가하거나 삭제하세요.", self,
        ))

        self.search_edit = SearchLineEdit(self)
        self.search_edit.setPlaceholderText("예: 수원, 강남구, 안동시")
        self.search_edit.textChanged.connect(self._render_results)
        outer.addWidget(self.search_edit)

        self.scroll = ScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.results_frame = QWidget()
        self.results_frame.setStyleSheet("background: transparent;")
        self.results_layout = QVBoxLayout(self.results_frame)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_layout.setSpacing(theme.SPACE_1)
        self.results_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.results_frame)
        outer.addWidget(self.scroll, 1)

        add_btn = PushButton("위도·경도로 직접 추가", self, FluentIcon.PIN)
        add_btn.setToolTip("지도에서 확인한 위도·경도로 새 지역을 추가합니다")
        add_btn.clicked.connect(self._open_custom_region_form)
        close_btn = PushButton("닫기", self)
        close_btn.clicked.connect(self.close)
        # Footer 버튼 정렬 규칙(취소/보조가 왼쪽, 주 행동이 오른쪽)과는 다른
        # 성격의 화면이라 "직접 추가"는 왼쪽에 별도로 두고, 우측은 "닫기" 단독
        # (Primary 버튼이 없는 화면이라 닫기는 중립 스타일 그대로).
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(theme.SPACE_2)
        footer.addWidget(add_btn)
        footer.addStretch(1)
        footer.addWidget(close_btn)
        footer_wrap = QVBoxLayout()
        footer_wrap.setContentsMargins(0, 0, 0, 0)
        footer_wrap.setSpacing(theme.SPACE_3)
        footer_divider = QFrame(self)
        footer_divider.setFixedHeight(1)
        footer_wrap.addWidget(footer_divider)
        footer_wrap.addLayout(footer)
        outer.addLayout(footer_wrap)

        def _restyle_footer_divider():
            fc = theme.colors()
            footer_divider.setStyleSheet(f"background-color:{fc['divider']};")

        _restyle_footer_divider()
        self._on_theme_refresh(_restyle_footer_divider)
        self._result_theme_refresh = []
        self._on_theme_refresh(self._refresh_result_rows)

        self._render_results()
        _bring_to_front(self)

    def _current_matches(self):
        query = self.search_edit.text().strip()
        all_regions = regions.all_regions()
        if not query:
            names = sorted(self.favorites)
        else:
            names = sorted(n for n in all_regions if query in n)
        return names[:80]

    def _refresh_result_rows(self):
        """_render_results()가 매번 새로 만드는 행들의 테마 재적용 콜백 -
        검색어가 바뀔 때마다 _render_results()가 다시 불리므로, 이전 행을
        가리키는 콜백이 self._extra_theme_refresh에 계속 쌓이지 않도록 이
        목록(self._result_theme_refresh)은 매번 새로 비우고 이 메서드
        하나만 다이얼로그 수명 동안 한 번 등록해 항상 "현재" 목록을 읽는다."""
        for callback in getattr(self, "_result_theme_refresh", []):
            callback()

    def _render_results(self, *_args):
        _clear_layout(self.results_layout)
        self._result_theme_refresh = []

        query = self.search_edit.text().strip()
        names = self._current_matches()
        if not query and not names:
            empty = uic.EmptyState(
                "아직 즐겨찾기가 없습니다", "위 검색창에 지역명을 입력해 추가하세요.", self.results_frame,
            )
            self.results_layout.addWidget(empty)
            return
        if query and not names:
            empty = uic.EmptyState(
                "검색 결과가 없습니다", f'"{query}"와(과) 일치하는 지역이 없습니다.', self.results_frame,
            )
            self.results_layout.addWidget(empty)
            return

        custom_names = set(regions.load_custom_regions().keys())
        metrics = QFontMetrics(self.font_body)
        for name in names:
            is_favorite = name in self.favorites
            row = QFrame(self.results_frame)
            row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(theme.SPACE_2, theme.SPACE_1, theme.SPACE_2, theme.SPACE_1)
            row_layout.setSpacing(theme.SPACE_2)

            label_text = name + ("  ·  직접 추가" if name in custom_names else "")
            elided = metrics.elidedText(label_text, Qt.TextElideMode.ElideRight, 320)
            checkbox = CheckBox(elided, row)
            checkbox.setFont(self.font_body)
            checkbox.setToolTip(label_text)
            checkbox.setChecked(is_favorite)
            checkbox.stateChanged.connect(lambda _state, n=name, cb=checkbox: self._toggle(n, cb))
            row_layout.addWidget(checkbox, 1)

            if is_favorite:
                delete_btn = uic.DangerHoverIconButton(FluentIcon.DELETE, tooltip=f"{name} 즐겨찾기에서 삭제", parent=row)
                delete_btn.setAccessibleName(f"{name} 즐겨찾기에서 삭제")
                # 기존 삭제 동작(_toggle의 else 분기) 그대로 재사용 - 체크박스를
                # 해제시키는 것으로 트리거해 새 삭제 로직을 만들지 않는다.
                delete_btn.clicked.connect(lambda _c=False, cb=checkbox: cb.setChecked(False))
                row_layout.addWidget(delete_btn)

            def _restyle_row(row=row, is_favorite=is_favorite):
                rc = theme.colors()
                bg = rc["surface_selected"] if is_favorite else "transparent"
                row.setStyleSheet(f"QFrame {{ background-color:{bg}; border:none; border-radius:{theme.RADIUS_CONTROL}px; }}")

            _restyle_row()
            self._result_theme_refresh.append(_restyle_row)
            self.results_layout.addWidget(row)

    def _toggle(self, name, checkbox):
        if checkbox.isChecked():
            self.favorites.add(name)
            config.set_favorites(sorted(self.favorites))
            self.on_change(added=name)
        else:
            self.favorites.discard(name)
            config.set_favorites(sorted(self.favorites))
            self.on_change(removed=name)
        self._render_results()

    def _open_custom_region_form(self):
        # 이전에는 .exec()/.show()를 부르지 않아 다이얼로그가 생성만 되고
        # 화면에 뜨지 않는 회귀가 있었다(다른 모든 다이얼로그는 .exec() 사용).
        CustomRegionForm(self, self._render_results).exec()


class CustomRegionForm(_ThemedDialog):
    """좌표 검증(float 파싱)·grid 변환(regions.add_custom_region)·저장 순서는
    그대로 두고, 오류 표시만 QMessageBox 팝업에서 필드 옆 인라인 오류로 바꾼다."""

    def __init__(self, parent, on_saved):
        super().__init__(parent)
        self.setWindowTitle("지역 직접 추가")
        self._bind_background()
        self.setMinimumWidth(420)
        self.on_saved = on_saved

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            theme.DIALOG_CONTENT_MARGIN, theme.DIALOG_CONTENT_MARGIN,
            theme.DIALOG_CONTENT_MARGIN, theme.DIALOG_CONTENT_MARGIN,
        )
        outer.setSpacing(theme.SPACE_5)

        outer.addWidget(uic.DialogHeader(
            "지역 직접 추가", "위도·경도를 아는 위치를 즐겨찾기에 새로 등록합니다.", self,
        ))

        content = QVBoxLayout()
        content.setSpacing(theme.SPACE_4)

        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText("예: 진천군")
        self.name_field = uic.FormField("지역 이름", self.name_edit, required=True, parent=self)
        content.addWidget(self.name_field)

        self.lat_edit = LineEdit(self)
        self.lat_edit.setPlaceholderText("예: 36.855")
        self.lat_field = uic.FormField("위도", self.lat_edit, required=True, parent=self)
        content.addWidget(self.lat_field)

        self.lon_edit = LineEdit(self)
        self.lon_edit.setPlaceholderText("예: 127.435")
        self.lon_field = uic.FormField("경도", self.lon_edit, required=True, parent=self)
        content.addWidget(self.lon_field)

        self.sido_combo = ComboBox(self)
        self.sido_combo.addItems(regions.SIDO_NAMES)
        self.sido_field = uic.FormField(
            "시도", self.sido_combo, helper_text="중기예보 권역을 구분하는 데 쓰입니다.", parent=self,
        )
        content.addWidget(self.sido_field)
        outer.addLayout(content)

        self._hint_label = QLabel(
            "위도·경도는 구글맵 등 지도에서 원하는 위치를 우클릭하면 확인할 수 있습니다.", self,
        )
        self._hint_label.setFont(theme.font_role("caption"))
        self._hint_label.setWordWrap(True)
        outer.addWidget(self._hint_label)

        outer.addStretch(1)

        cancel_btn = PushButton("취소", self)
        cancel_btn.clicked.connect(self.close)
        save_btn = PrimaryPushButton("추가", self)
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        outer.addWidget(uic.DialogFooter([cancel_btn, save_btn], parent=self))

        self.setTabOrder(self.name_edit, self.lat_edit)
        self.setTabOrder(self.lat_edit, self.lon_edit)
        self.setTabOrder(self.lon_edit, self.sido_combo)
        self.setTabOrder(self.sido_combo, cancel_btn)
        self.setTabOrder(cancel_btn, save_btn)

        self._refresh_hint_style()
        self._on_theme_refresh(self._refresh_hint_style)

        _bring_to_front(self)

    def _refresh_hint_style(self):
        c = theme.colors()
        self._hint_label.setStyleSheet(f"color:{c['text_tertiary']}; background:transparent; border:none;")

    def _save(self):
        name = self.name_edit.text().strip()
        lat_text = self.lat_edit.text().strip()
        lon_text = self.lon_edit.text().strip()

        first_invalid = None
        if name:
            self.name_field.clear_error()
        else:
            self.name_field.set_error("지역 이름을 입력하세요.")
            first_invalid = first_invalid or self.name_edit

        lat = lon = None
        try:
            lat = float(lat_text)
            self.lat_field.clear_error()
        except ValueError:
            self.lat_field.set_error("위도는 숫자로 입력하세요.")
            first_invalid = first_invalid or self.lat_edit
        try:
            lon = float(lon_text)
            self.lon_field.clear_error()
        except ValueError:
            self.lon_field.set_error("경도는 숫자로 입력하세요.")
            first_invalid = first_invalid or self.lon_edit

        if first_invalid is not None:
            first_invalid.setFocus()
            return

        regions.add_custom_region(name, lat, lon, self.sido_combo.currentText())
        config.add_favorite(name)
        self.parent().favorites.add(name)
        self.on_saved()
        self.parent().on_change(added=name)
        toast(self.parent(), "success", "추가됨", f"'{name}'을(를) 즐겨찾기에 추가했습니다.")
        self.close()


class BranchRangeDialog(_ThemedDialog):
    """지사 이름을 클릭하면 뜨는 창: 날짜와 시간대(시작~종료)를 골라 그 구간의
    누적강수량을 지사 관할 지역별로 비교하고, 가장 많은 지역을 하이라이트한다.
    지난 실측 2일 + 단기예보 날짜를 고를 수 있다. 중기예보(4일 이후)는 3시간 단위
    시간별 데이터를 제공하지 않아 날짜 선택 대상에서 제외한다. 날짜/시간대 선택
    로직과 누적강수량 계산(kma_client.sum_pcp_range 등)은 그대로 두고, 결과
    표시만 오른쪽 정렬 수치 + accent 강조(경고색이 아님 - "많은 비=위험"이라는
    임의 기준을 만들지 않기 위해 danger/warning 대신 accent_soft를 쓴다)로 바꾼다."""

    def __init__(self, parent, branch_name, members, reports):
        super().__init__(parent)
        self.branch_name = branch_name
        self.members = members
        self.reports = reports
        self.font_body = parent.font_body
        self.font_small = parent.font_small
        self.setWindowTitle(f"{branch_name} - 시간대별 누적강수량")
        self._bind_background()
        self.setMinimumSize(480, 560)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            theme.DIALOG_CONTENT_MARGIN, theme.DIALOG_CONTENT_MARGIN,
            theme.DIALOG_CONTENT_MARGIN, theme.DIALOG_CONTENT_MARGIN,
        )
        outer.setSpacing(theme.SPACE_4)

        outer.addWidget(uic.DialogHeader(
            branch_name,
            "선택한 날짜·시간대의 관할 지역별 누적강수량을 비교합니다. "
            "(지난 실측 2일 + 단기예보만 선택 가능 - 중기예보는 시간별 데이터가 없습니다)",
            self,
        ))

        self.dates = self._short_term_dates()

        if not self.dates:
            empty = uic.EmptyState(
                "선택 가능한 날짜가 없습니다",
                "즐겨찾기 조회가 끝난 뒤 다시 시도해 주세요.",
                self,
            )
            outer.addWidget(empty, 1)
            close_btn = PushButton("닫기", self)
            close_btn.clicked.connect(self.close)
            outer.addWidget(uic.DialogFooter([close_btn], parent=self))
            _bring_to_front(self)
            return

        picker_row = QHBoxLayout()
        picker_row.setSpacing(theme.SPACE_3)
        self._date_hdr = QLabel("날짜", self)
        self._date_hdr.setFont(self.font_body)
        picker_row.addWidget(self._date_hdr)

        self.date_seg = SegmentedWidget(self)
        for d in self.dates:
            self.date_seg.addItem(d, f"{d[4:6]}/{d[6:8]}", onClick=lambda _c=False, dd=d: self._on_date_changed(dd))
        picker_row.addWidget(self.date_seg, 1)
        outer.addLayout(picker_row)

        time_row = QHBoxLayout()
        time_row.setSpacing(theme.SPACE_3)
        self._start_hdr = QLabel("시작", self)
        self._start_hdr.setFont(self.font_body)
        time_row.addWidget(self._start_hdr)
        self.start_combo = ComboBox(self)
        self.start_combo.currentTextChanged.connect(lambda _v: self._render())
        time_row.addWidget(self.start_combo)
        self._end_hdr = QLabel("종료", self)
        self._end_hdr.setFont(self.font_body)
        time_row.addWidget(self._end_hdr)
        self.end_combo = ComboBox(self)
        self.end_combo.currentTextChanged.connect(lambda _v: self._render())
        time_row.addWidget(self.end_combo)
        time_row.addStretch(1)
        outer.addLayout(time_row)

        self.result_scroll = ScrollArea(self)
        self.result_scroll.setWidgetResizable(True)
        self.result_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        result_frame = QWidget()
        result_frame.setStyleSheet("background: transparent;")
        self.result_layout = QVBoxLayout(result_frame)
        self.result_layout.setContentsMargins(0, 0, 0, 0)
        self.result_layout.setSpacing(theme.SPACE_1)
        self.result_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.result_scroll.setWidget(result_frame)
        outer.addWidget(self.result_scroll, 1)

        close_btn = PushButton("닫기", self)
        close_btn.clicked.connect(self.close)
        outer.addWidget(uic.DialogFooter([close_btn], parent=self))

        def _restyle_pickers():
            pc = theme.colors()
            for hdr in (self._date_hdr, self._start_hdr, self._end_hdr):
                hdr.setStyleSheet(f"color:{pc['text_secondary']}; background:transparent; border:none;")

        _restyle_pickers()
        self._on_theme_refresh(_restyle_pickers)
        self._result_theme_refresh = []
        self._on_theme_refresh(self._refresh_result_rows)

        self.date_seg.setCurrentItem(self.dates[0])
        self._on_date_changed(self.dates[0])
        _bring_to_front(self)

    def _short_term_dates(self):
        """관할 지역 중 시간별 데이터가 있는 날짜(지난 실측 + 단기예보)만 모아
        정렬해서 반환한다. 중기예보(4일 이후)는 3시간 단위 시간별 데이터가 없어 제외."""
        dates = []
        seen = set()
        for name in self.members:
            report = self.reports.get(name)
            if not report:
                continue
            for day in report.get("forecast", []):
                d = day.get("date")
                if d and d not in seen and day.get("source") in ("단기예보", "실측"):
                    seen.add(d)
                    dates.append(d)
        dates.sort()
        return dates

    def _hour_options(self, date_str):
        """해당 날짜에 관할 지역들의 시간별 예보에 실제로 존재하는 시각(시 단위) 목록."""
        hours = set()
        for name in self.members:
            report = self.reports.get(name)
            if not report:
                continue
            day = next((d for d in report.get("forecast", []) if d.get("date") == date_str), None)
            if not day:
                continue
            for hour in day.get("hourly") or []:
                t = hour.get("time")
                if t and len(t) >= 2:
                    hours.add(int(t[:2]))
        return sorted(hours)

    def _on_date_changed(self, date_str):
        self._current_date = date_str
        hours = self._hour_options(date_str)
        start_values = [f"{h:02d}시" for h in hours]
        end_values = [f"{h:02d}시" for h in hours[1:]] + ["24시"]
        self.start_combo.blockSignals(True)
        self.end_combo.blockSignals(True)
        self.start_combo.clear()
        self.start_combo.addItems(start_values or ["-"])
        self.end_combo.clear()
        self.end_combo.addItems(end_values or ["-"])
        if end_values:
            self.end_combo.setCurrentIndex(len(end_values) - 1)
        self.start_combo.blockSignals(False)
        self.end_combo.blockSignals(False)
        self._render()

    def _selected_hour(self, label):
        if not label or label == "-":
            return None
        return int(label[:2])

    def _refresh_result_rows(self):
        """_render()가 매번 새로 만드는 result_layout 내용물의 테마 재적용
        콜백만 모아 둔 별도 목록 - self._extra_theme_refresh(다이얼로그 수명
        내내 누적)에 직접 쌓으면 _render()를 다시 부를 때마다 이미 지워진
        이전 행 위젯을 가리키는 콜백이 계속 남아 다음 테마 전환에서 삭제된
        C++ 객체를 건드리게 된다. 그래서 이 목록은 _render()가 매번 새로
        비우고, 다이얼로그 수명 동안엔 이 메서드 하나만 _extra_theme_refresh에
        등록해 항상 "현재" 목록을 읽게 한다."""
        for callback in getattr(self, "_result_theme_refresh", []):
            callback()

    def _render(self):
        _clear_layout(self.result_layout)
        self._result_theme_refresh = []

        date_str = getattr(self, "_current_date", None)
        start_hour = self._selected_hour(self.start_combo.currentText())
        end_hour = self._selected_hour(self.end_combo.currentText())
        if date_str is None or start_hour is None or end_hour is None:
            return
        if start_hour >= end_hour:
            warn = uic.InlineBanner("시작 시각은 종료 시각보다 앞서야 합니다.", level="warning", parent=self)
            self.result_layout.addWidget(warn)
            return

        rows = []
        best_name, best_amount = None, -1.0
        for name in self.members:
            report = self.reports.get(name)
            day = None
            if report:
                day = next((d for d in report.get("forecast", []) if d.get("date") == date_str), None)
            if day is None:
                pcp_text, amount = "-", -1.0
            else:
                slot_pcp = [
                    h.get("pcp") for h in (day.get("hourly") or [])
                    if h.get("time") and start_hour <= int(h["time"][:2]) < end_hour
                ]
                pcp_text = kma_client.sum_pcp_range(slot_pcp) if slot_pcp else "강수없음"
                amount = _pcp_numeric(pcp_text)
            rows.append((name, pcp_text, amount))
            if amount > best_amount:
                best_amount = amount
                best_name = name

        header = QLabel(
            f"{date_str[4:6]}/{date_str[6:8]}  {start_hour:02d}시~{end_hour:02d}시 누적강수량", self
        )
        header.setFont(theme.font_role("label"))

        def _restyle_header(header=header):
            hc = theme.colors()
            header.setStyleSheet(f"color:{hc['text_secondary']}; background:transparent; border:none;")

        _restyle_header()
        self._result_theme_refresh.append(_restyle_header)
        self.result_layout.addWidget(header)

        # 최다 강수 지역은 계산 결과(best_name/best_amount)만 그대로 강조한다 -
        # danger/warning처럼 "위험"을 뜻하는 색 대신 accent_soft(단순 강조)를
        # 써서 "비가 많이 온 지역=위험"이라는 임의 기준을 만들지 않는다.
        for name, pcp_text, amount in rows:
            is_best = name == best_name and best_amount > 0
            row = QFrame(self)
            row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_3, theme.SPACE_2)
            name_label = QLabel(name, row)
            name_label.setFont(theme.font_role("body_medium" if is_best else "body"))
            row_layout.addWidget(name_label, 1)
            value_label = QLabel(("★ " if is_best else "") + pcp_text, row)
            value_label.setFont(theme.font_role("body_medium" if is_best else "body"))
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row_layout.addWidget(value_label)
            self.result_layout.addWidget(row)

            def _restyle_result_row(row=row, name_label=name_label, value_label=value_label, is_best=is_best):
                rc = theme.colors()
                bg = rc["accent_soft"] if is_best else "transparent"
                fg = rc["accent"] if is_best else rc["text_primary"]
                row.setStyleSheet(f"QFrame {{ background-color:{bg}; border:none; border-radius:{theme.RADIUS_CONTROL}px; }}")
                name_label.setStyleSheet(f"color:{fg}; background:transparent; border:none;")
                value_label.setStyleSheet(f"color:{fg}; background:transparent; border:none;")

            _restyle_result_row()
            self._result_theme_refresh.append(_restyle_result_row)


class AddBranchDialog(_ThemedDialog):
    """새 지사 이름을 입력받는 작은 다이얼로그. 기본 QInputDialog.getText()
    팝업은 앱 테마를 따르지 않고 빈 이름/중복 이름 검증도 못 해, 이름을
    입력받고 확인 시점에 InlineBanner로(다이얼로그를 닫지 않고) 오류를
    보여준다."""

    def __init__(self, parent, existing_names):
        super().__init__(parent)
        self.setWindowTitle("새 지사 추가")
        self._bind_background()
        self.setMinimumWidth(360)
        self._existing_names = set(existing_names)
        self.result_name = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            theme.DIALOG_CONTENT_MARGIN, theme.DIALOG_CONTENT_MARGIN,
            theme.DIALOG_CONTENT_MARGIN, theme.DIALOG_CONTENT_MARGIN,
        )
        outer.setSpacing(theme.SPACE_3)

        outer.addWidget(uic.DialogHeader("새 지사 추가", "지사 이름을 입력하세요.", self))

        self._name_edit = LineEdit(self)
        self._name_edit.setPlaceholderText("지사 이름")
        self._name_edit.setAccessibleName("지사 이름")
        self._name_edit.returnPressed.connect(self._on_confirm)
        outer.addWidget(self._name_edit)

        self._error_banner = uic.InlineBanner("", level="danger", parent=self)
        self._error_banner.setVisible(False)
        outer.addWidget(self._error_banner)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = PushButton("취소", self)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        confirm_btn = PrimaryPushButton("추가", self)
        confirm_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(confirm_btn)
        outer.addLayout(btn_row)

        self._name_edit.setFocus()

    def _on_confirm(self):
        name = self._name_edit.text().strip()
        if not name:
            self._show_error("지사 이름을 입력하세요.")
            return
        if name in self._existing_names:
            self._show_error(f"'{name}' 지사가 이미 있습니다.")
            return
        self.result_name = name
        self.accept()

    def _show_error(self, text):
        self._error_banner.set_message(text)
        self._error_banner.setVisible(True)


class BranchManagerDialog(_ThemedDialog):
    """지사(관할 구역) 관리: 지사별로 어떤 즐겨찾기 지역이 속하는지 편집.
    '즐겨찾기 종합 보기'에서 지사 단위로 묶어서 보여주는 데 쓰인다.

    지사 추가·삭제·지역 배정/해제 로직(config.add_branch/remove_branch/
    add_region_to_branch/remove_region_from_branch, 검색 일치 검증)은 그대로
    두고, "지사 목록(왼쪽) / 선택한 지사의 배정 지역(오른쪽)" 좌우 분할로 관계를
    분명히 한다 - 지사당 카드+인라인 검색창을 세로로 늘어놓던 예전 구조 대신,
    지금 편집 중인 지사가 항상 하나로 명확하다."""

    def __init__(self, parent, on_change):
        super().__init__(parent)
        self.setWindowTitle("지사 관리")
        self._bind_background()
        # 검색 결과 없음/여러 개 일치 안내(InlineBanner)+후보 목록이 이제
        # 팝업이 아니라 오른쪽 패널 안에 자리를 차지하므로(Section 14), 예전
        # 높이(540)로는 그 상태에서 위쪽 지역 목록 영역이 과하게 눌렸다.
        self.setMinimumSize(600, 620)
        self.on_change = on_change
        self.font_body = parent.font_body
        self.font_small = parent.font_small
        self.selected_branch = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            theme.DIALOG_CONTENT_MARGIN, theme.DIALOG_CONTENT_MARGIN,
            theme.DIALOG_CONTENT_MARGIN, theme.DIALOG_CONTENT_MARGIN,
        )
        outer.setSpacing(theme.SPACE_4)

        outer.addWidget(uic.DialogHeader(
            "지사 관리",
            "지사별로 즐겨찾기 지역을 묶어서 관리합니다. 지역 하나가 여러 지사에 동시에 속할 수도 있습니다.",
            self,
        ))

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setHandleWidth(theme.SPACE_1)
        splitter.setChildrenCollapsible(False)
        self._splitter = splitter

        # ---------- 왼쪽: 지사 목록 ----------
        left = QWidget(splitter)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(theme.SPACE_2)

        add_branch_btn = PushButton("새 지사 추가", left, FluentIcon.ADD)
        add_branch_btn.clicked.connect(self._add_branch)
        left_layout.addWidget(add_branch_btn)

        self.branch_stack = QStackedWidget(left)
        self.branch_list = ListWidget(self.branch_stack)
        self.branch_list.setFrameShape(QFrame.Shape.NoFrame)
        self.branch_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.branch_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.branch_list.itemClicked.connect(self._on_branch_item_clicked)
        self._style_branch_list()
        self._on_theme_refresh(self._style_branch_list)
        self.branch_stack.addWidget(self.branch_list)
        self.branch_empty_state = uic.EmptyState(
            "아직 지사가 없습니다", "위 버튼으로 첫 지사를 만드세요.", self.branch_stack,
        )
        self.branch_stack.addWidget(self.branch_empty_state)
        left_layout.addWidget(self.branch_stack, 1)

        left.setMinimumWidth(180)
        left.setMaximumWidth(240)
        splitter.addWidget(left)

        # ---------- 오른쪽: 선택한 지사의 배정 지역 ----------
        right = QWidget(splitter)
        self.right_layout = QVBoxLayout(right)
        self.right_layout.setContentsMargins(0, 0, 0, 0)
        self.right_layout.setSpacing(theme.SPACE_3)
        splitter.addWidget(right)
        self._right_theme_refresh = []
        self._on_theme_refresh(self._refresh_right_panel_theme)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, 1)

        close_btn = PushButton("닫기", self)
        close_btn.clicked.connect(self.close)
        outer.addWidget(uic.DialogFooter([close_btn], parent=self))

        self._render()
        _bring_to_front(self)

    def _style_branch_list(self):
        c = theme.colors()
        self.branch_list.setStyleSheet(f"""
            QListWidget {{ background: transparent; border: none; outline: none; }}
            QListWidget::item {{
                padding: 0px {theme.SPACE_3}px; border-radius: {theme.RADIUS_CONTROL}px;
                color: {c['text_primary']};
            }}
            QListWidget::item:hover {{ background-color: {c['surface_hover']}; }}
            QListWidget::item:selected {{
                background-color: {c['surface_selected']}; color: {c['text_primary']}; font-weight: 500;
            }}
            QListWidget::item:focus {{
                border: {theme.FOCUS_RING_WIDTH}px solid {c['focus']};
            }}
        """)

    def _on_branch_item_clicked(self, item):
        self.selected_branch = item.data(Qt.ItemDataRole.UserRole)
        self._render_right_panel()

    # ---------- 렌더링 ----------
    def _render(self):
        """지사 목록(왼쪽)을 다시 그린다 - 지사 추가/삭제 뒤에만 부르고,
        지역 배정만 바뀐 경우엔 _render_right_panel()만 다시 부르면 된다."""
        branches = config.get_branches()
        names = sorted(branches)

        if not names:
            self.selected_branch = None
            self.branch_stack.setCurrentWidget(self.branch_empty_state)
            self._render_right_panel()
            return
        self.branch_stack.setCurrentWidget(self.branch_list)

        if self.selected_branch not in names:
            self.selected_branch = names[0]

        self.branch_list.clear()
        for name in names:
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip(name)
            item.setSizeHint(QSize(0, 36))
            self.branch_list.addItem(item)
            if name == self.selected_branch:
                self.branch_list.setCurrentItem(item)

        self._render_right_panel()

    def _refresh_right_panel_theme(self):
        """_render_right_panel()이 매번 새로 만드는 위젯들의 테마 재적용
        콜백 - 지사 선택/지역 추가·삭제마다 다시 불리므로, 이전 행을 가리키는
        콜백이 self._extra_theme_refresh에 계속 쌓이지 않도록 이 목록은 매번
        새로 비우고 이 메서드 하나만 다이얼로그 수명 동안 한 번 등록한다."""
        for callback in getattr(self, "_right_theme_refresh", []):
            callback()

    def _render_right_panel(self):
        _clear_layout(self.right_layout)
        self._right_theme_refresh = []
        branches = config.get_branches()

        if self.selected_branch is None or self.selected_branch not in branches:
            empty = uic.EmptyState(
                "지사를 선택하세요", "왼쪽 목록에서 지사를 선택하면 배정된 지역을 관리할 수 있습니다.",
                self,
            )
            self.right_layout.addWidget(empty, 1)
            return

        branch_name = self.selected_branch
        region_names = branches[branch_name]

        header_row = QHBoxLayout()
        header_row.setSpacing(theme.SPACE_2)
        name_label = QLabel(branch_name, self)
        name_label.setFont(theme.font_role("card_title"))
        header_row.addWidget(name_label, 1)
        del_branch_btn = uic.DangerHoverIconButton(
            FluentIcon.DELETE, tooltip=f"{branch_name} 지사 삭제", parent=self,
        )
        del_branch_btn.setAccessibleName(f"{branch_name} 지사 삭제")
        del_branch_btn.clicked.connect(lambda _c=False, b=branch_name: self._remove_branch(b))
        header_row.addWidget(del_branch_btn)
        self.right_layout.addLayout(header_row)

        def _restyle_name_label(name_label=name_label):
            nc = theme.colors()
            name_label.setStyleSheet(f"color:{nc['text_primary']}; background:transparent; border:none;")

        _restyle_name_label()
        self._right_theme_refresh.append(_restyle_name_label)

        region_scroll = ScrollArea(self)
        region_scroll.setWidgetResizable(True)
        region_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        region_frame = QWidget()
        region_frame.setStyleSheet("background: transparent;")
        region_layout = QVBoxLayout(region_frame)
        region_layout.setContentsMargins(0, 0, 0, 0)
        region_layout.setSpacing(theme.SPACE_1)
        region_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        if not region_names:
            # "지사가 없음"과는 다른 상태 - 지사는 있지만 배정된 지역이 없는
            # 경우라, 배너 문구도 다르게 안내한다.
            hint = uic.InlineBanner(
                "이 지사에 배정된 지역이 없습니다. 아래에서 즐겨찾기 지역을 검색해 추가하세요.",
                level="info", parent=region_frame,
            )
            region_layout.addWidget(hint)
        else:
            for region_name in region_names:
                row = QFrame(region_frame)
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(theme.SPACE_2, theme.SPACE_1, theme.SPACE_2, theme.SPACE_1)
                region_label = QLabel(region_name, row)
                region_label.setFont(self.font_body)
                row_layout.addWidget(region_label, 1)
                remove_btn = uic.DangerHoverIconButton(
                    FluentIcon.REMOVE, tooltip=f"{region_name} 배정 해제", parent=row,
                )
                remove_btn.setAccessibleName(f"{region_name} 배정 해제")
                remove_btn.clicked.connect(
                    lambda _c=False, b=branch_name, r=region_name: self._remove_region(b, r)
                )
                row_layout.addWidget(remove_btn)

                def _restyle_region_label(region_label=region_label):
                    rc = theme.colors()
                    region_label.setStyleSheet(f"color:{rc['text_primary']}; background:transparent; border:none;")

                _restyle_region_label()
                self._right_theme_refresh.append(_restyle_region_label)
                region_layout.addWidget(row)

        region_scroll.setWidget(region_frame)
        self.right_layout.addWidget(region_scroll, 1)

        add_row = QHBoxLayout()
        add_row.setSpacing(theme.SPACE_2)
        search_edit = LineEdit(self)
        search_edit.setPlaceholderText("즐겨찾기 지역 검색해서 추가")
        search_edit.returnPressed.connect(
            lambda b=branch_name, e=search_edit: self._add_region_from_search(b, e)
        )
        add_row.addWidget(search_edit, 1)
        add_region_btn = PushButton("추가", self)
        add_region_btn.clicked.connect(
            lambda _c=False, b=branch_name, e=search_edit: self._add_region_from_search(b, e)
        )
        add_row.addWidget(add_region_btn)
        self.right_layout.addLayout(add_row)

        # 검색 결과 없음/여러 개 일치를 기본 QMessageBox 팝업 대신 인라인으로
        # 보여준다 - "여러 개 일치"는 첫 번째를 임의로 골라 추가하지 않고
        # 후보를 목록으로 보여줘 사용자가 직접 고르게 한다.
        self._region_search_banner = uic.InlineBanner("", level="warning", parent=self)
        self._region_search_banner.setVisible(False)
        self.right_layout.addWidget(self._region_search_banner)

        self._region_search_candidates = ListWidget(self)
        self._region_search_candidates.setFrameShape(QFrame.Shape.NoFrame)
        self._region_search_candidates.setMaximumHeight(120)
        self._region_search_candidates.setVisible(False)
        self._region_search_candidates.itemClicked.connect(self._on_region_candidate_selected)
        self.right_layout.addWidget(self._region_search_candidates)

    def _add_region_from_search(self, branch_name, search_edit):
        self._region_search_candidates.clear()
        self._region_search_candidates.setVisible(False)
        query = search_edit.text().strip()
        if not query:
            self._region_search_banner.setVisible(False)
            return
        favorites = config.get_favorites()
        matches = [n for n in favorites if query in n]
        if not matches:
            self._region_search_banner.set_message(
                "일치하는 즐겨찾기 지역이 없습니다. 먼저 즐겨찾기에 추가하세요.", level="warning",
            )
            self._region_search_banner.setVisible(True)
            return
        if len(matches) > 1:
            self._region_search_banner.set_message(
                "검색어와 일치하는 지역이 여러 개입니다. 추가할 지역을 아래 목록에서 선택하세요.",
                level="info",
            )
            self._region_search_banner.setVisible(True)
            for name in matches:
                item = QListWidgetItem(name)
                item.setData(Qt.ItemDataRole.UserRole, (branch_name, name))
                self._region_search_candidates.addItem(item)
            self._region_search_candidates.setVisible(True)
            return
        self._region_search_banner.setVisible(False)
        config.add_region_to_branch(branch_name, matches[0])
        self._render_right_panel()
        self.on_change()

    def _on_region_candidate_selected(self, item):
        branch_name, region_name = item.data(Qt.ItemDataRole.UserRole)
        config.add_region_to_branch(branch_name, region_name)
        self._render_right_panel()
        self.on_change()

    def _remove_region(self, branch_name, region_name):
        config.remove_region_from_branch(branch_name, region_name)
        self._render_right_panel()
        self.on_change()

    def _remove_branch(self, branch_name):
        config.remove_branch(branch_name)
        self.selected_branch = None
        self._render()
        self.on_change()

    def _add_branch(self):
        dlg = AddBranchDialog(self, config.get_branches().keys())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name = dlg.result_name
        config.add_branch(name)
        self.selected_branch = name
        self._render()
        self.on_change()
        toast(self.parent(), "success", "지사 추가됨", f"'{name}' 지사를 추가했습니다.")


class SettingsDialog(_ThemedDialog):
    """서비스키 저장 위치(config.set_service_key)와 "키 표시" 로직은 그대로
    두고, 서비스키 입력을 label+helper text로 묶은 FormField 하나로 표준
    Header/Content/Footer 구조에 얹는다."""

    def __init__(self, parent, on_change):
        super().__init__(parent)
        self.setWindowTitle("설정 - 기상청 서비스키")
        self._bind_background()
        self.setMinimumWidth(460)
        self.on_change = on_change

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            theme.DIALOG_CONTENT_MARGIN, theme.DIALOG_CONTENT_MARGIN,
            theme.DIALOG_CONTENT_MARGIN, theme.DIALOG_CONTENT_MARGIN,
        )
        outer.setSpacing(theme.SPACE_5)

        outer.addWidget(uic.DialogHeader(
            "기상청 API 서비스키",
            "공공데이터포털(data.go.kr)에서 발급받은 서비스키(디코딩 키)로 실시간·예보 데이터를 조회합니다.",
            self,
        ))

        self.key_edit = LineEdit(self)
        self.key_edit.setText(config.get_service_key())
        self.key_edit.setEchoMode(LineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("공공데이터포털 서비스키를 붙여넣으세요")
        self.key_field = uic.FormField(
            "기상청 API 서비스키", self.key_edit,
            helper_text="이 값은 이 컴퓨터의 설정 파일에만 저장되며, 외부로 전송되지 않습니다.",
            required=True, parent=self,
        )
        outer.addWidget(self.key_field)

        self.show_checkbox = CheckBox("키 표시", self)
        self.show_checkbox.setToolTip("서비스키를 평문으로 표시합니다")
        self.show_checkbox.stateChanged.connect(self._toggle_show)
        outer.addWidget(self.show_checkbox)

        outer.addStretch(1)

        cancel_btn = PushButton("취소", self)
        cancel_btn.clicked.connect(self.close)
        save_btn = PrimaryPushButton("저장", self)
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        outer.addWidget(uic.DialogFooter([cancel_btn, save_btn], parent=self))

        self.setTabOrder(self.key_edit, self.show_checkbox)
        self.setTabOrder(self.show_checkbox, cancel_btn)
        self.setTabOrder(cancel_btn, save_btn)

        _bring_to_front(self)

    def _toggle_show(self):
        self.key_edit.setEchoMode(
            LineEdit.EchoMode.Normal if self.show_checkbox.isChecked() else LineEdit.EchoMode.Password
        )

    def _save(self):
        # 기존 검증 규칙 그대로: 빈 키도 저장을 막지 않는다(비워서 저장하면
        # 서비스키를 지우는 셈이 되는 기존 동작 유지).
        config.set_service_key(self.key_edit.text().strip())
        self.on_change()
        toast(self.parent(), "success", "저장됨", "서비스키를 저장했습니다.")
        self.close()


# ---------------------------------------------------------------------------
# 메인 윈도우
# ---------------------------------------------------------------------------


class _FetchBridge(QObject):
    all_done = Signal(int, object, object)
    one_done = Signal(str, object)


class WeatherDutyApp(QMainWindow):
    def __init__(self):
        super().__init__()
        theme.on_theme_changed(self._on_theme_changed)
        self._theme_listener = SystemThemeListener(self)
        self._theme_listener.start()

        self.setWindowTitle("폭염·풍수해·제설 근무 날씨 모니터")
        self.setWindowIcon(_build_app_icon())
        self.resize(1180, 700)
        self.setMinimumSize(960, 600)

        self.font_body = theme.font(13, QFont.Weight.Normal)
        self.font_small = theme.font(11, QFont.Weight.Normal)

        config.seed_default_branches_if_needed()

        self.selected_region = None
        self.reports = {}
        self.view_mode = "detail"
        self.selected_summary_date = None
        self._fetch_seq = 0

        self._bridge = _FetchBridge()
        self._bridge.all_done.connect(self._apply_fetch_result)
        self._bridge.one_done.connect(self._merge_one_report)

        central = QWidget(self)
        self.setCentralWidget(central)
        self.root_layout = QVBoxLayout(central)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)

        self._build_toolbar()
        self._build_layout()
        self._apply_window_style()

        QTimer.singleShot(200, self.refresh_all)

    def closeEvent(self, event):  # noqa: N802 - Qt override
        self._theme_listener.terminate()
        self._theme_listener.wait()
        super().closeEvent(event)

    def resizeEvent(self, event):  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._apply_header_compact_mode(event.size().width())

    def _apply_header_compact_mode(self, window_width):
        """창 폭이 HEADER_COMPACT_BREAKPOINT 미만이면 헤더 부제만 숨긴다
        (제목은 항상 그대로 보여준다) - 사이드바/여백을 뺀 콘텐츠 폭이 아니라
        창 전체 폭 기준으로 판단해도 무방할 만큼 여유(1050px)를 뒀다."""
        subtitle = getattr(self, "_header_subtitle_label", None)
        if subtitle is not None:
            subtitle.setVisible(window_width >= theme.HEADER_COMPACT_BREAKPOINT)

    # ---------- style ----------
    def _apply_window_style(self):
        self.centralWidget().setStyleSheet(f"background-color:{theme.colors()['bg']};")

    def _on_theme_changed(self):
        self._apply_window_style()
        self._rebuild_ui()

    def _rebuild_ui(self):
        # 팔레트가 바뀌면 위젯을 통째로 다시 만든다 (매번 렌더링 함수가 위젯을
        # 새로 그리는 이 앱의 구조를 그대로 활용한다). view_mode/selected_region/
        # selected_summary_date/sidebar 접힘 상태는 self(WeatherDutyApp
        # 인스턴스) 자체에 남아 있는 값이라 원래도 안전하지만, 위젯 자체가
        # 새로 만들어지며 초기화되는 값들(스플리터 크기, 스크롤 위치, 표 컬럼
        # 폭, 포커스)은 여기서 직접 붙잡아 뒀다가 다시 만든 뒤 되돌린다.
        state = self._capture_ui_state()

        old_central = self.centralWidget()
        central = QWidget(self)
        self.setCentralWidget(central)
        self.root_layout = QVBoxLayout(central)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)
        self._build_toolbar()
        self._build_layout()
        self._apply_window_style()
        old_central.setParent(None)
        old_central.deleteLater()
        self._sync_view_mode_widgets()
        self._refresh_current_view()
        self._restore_ui_state(state)

    def _capture_ui_state(self):
        """_rebuild_ui() 직전 스냅샷. view_mode 등 self에 이미 남아 있는 값은
        다시 캡처하지 않고, 위젯이 새로 만들어지며 사라지는 것들만 담는다:
        스플리터(사이드바) 크기, 일별예보/종합표 스크롤 위치, 종합표 지사 열
        폭, 현재 포커스가 놓여 있던(재구성 후에도 이름이 같은) 위젯."""
        favorites_list = getattr(self, "favorites_list", None)
        summary_table = getattr(self, "summary_table", None)
        summary_date_selector = getattr(self, "summary_date_selector", None)
        forecast_scroll = getattr(self, "forecast_scroll", None)
        splitter = getattr(self, "_body_splitter", None)

        focus_widget = QApplication.focusWidget()
        focus_role = None
        for role, widget in (
            ("favorites_list", favorites_list),
            ("summary_table", summary_table),
            ("summary_date_selector", summary_date_selector),
        ):
            if widget is not None and widget is focus_widget:
                focus_role = role
                break

        return {
            "splitter_sizes": splitter.sizes() if splitter is not None else None,
            "forecast_scroll_value": (
                forecast_scroll.verticalScrollBar().value() if forecast_scroll is not None else None
            ),
            "summary_table_scroll_value": (
                summary_table.verticalScrollBar().value() if summary_table is not None else None
            ),
            "summary_col0_width": (
                summary_table.columnWidth(0) if summary_table is not None else None
            ),
            "focus_role": focus_role,
        }

    def _restore_ui_state(self, state):
        """_capture_ui_state()가 찍어 둔 스냅샷을 새로 만들어진 위젯에 되돌린다.
        사이드바가 접힌 상태라면 스플리터 크기는 _apply_sidebar_collapsed_state()가
        이미 레일 폭으로 맞춰 뒀으므로 여기서 되돌리지 않는다."""
        if not state:
            return
        splitter = getattr(self, "_body_splitter", None)
        if splitter is not None and state.get("splitter_sizes") and not getattr(self, "_sidebar_collapsed", False):
            splitter.setSizes(state["splitter_sizes"])

        summary_table = getattr(self, "summary_table", None)
        if summary_table is not None and state.get("summary_col0_width"):
            summary_table.setColumnWidth(0, state["summary_col0_width"])

        role = state.get("focus_role")
        if role:
            widget = getattr(self, role, None)
            if widget is not None:
                widget.setFocus()

        # 스크롤 위치는 스크롤바 범위(콘텐츠 크기 기준)가 이 시점엔 아직 다음
        # 레이아웃 패스 전이라 유효하지 않다(범위가 계산되기 전이라 0으로
        # clamp됨) - 이벤트 루프가 한 번 돌고 레이아웃이 자리 잡은 뒤 적용되도록
        # 한 틱 미룬다. self를 통해 그 시점 위젯을 다시 찾아, 그 사이 또
        # 재구성(연속 테마 전환 등)돼 위젯이 이미 없어졌어도 안전하게 넘어간다.
        forecast_value = state.get("forecast_scroll_value")
        summary_value = state.get("summary_table_scroll_value")

        def _restore_scroll_positions():
            try:
                fc = getattr(self, "forecast_scroll", None)
                if fc is not None and forecast_value is not None:
                    fc.verticalScrollBar().setValue(forecast_value)
                st = getattr(self, "summary_table", None)
                if st is not None and summary_value is not None:
                    st.verticalScrollBar().setValue(summary_value)
            except RuntimeError:
                pass

        if forecast_value is not None or summary_value is not None:
            QTimer.singleShot(0, _restore_scroll_positions)

    # ---------- layout ----------
    def _build_toolbar(self):
        """상단 헤더: 왼쪽 제목/부제, 가운데 화면 전환, 오른쪽 상태·새로고침·설정.
        즐겨찾기 편집/지사 관리 버튼은 각각 사이드바 헤더와 종합보기 화면
        제목으로 옮겼다(콜백은 그대로 유지, _open_region_manager/_open_branch_manager).

        3분할 QGridLayout(왼쪽/가운데/오른쪽)을 쓴다 - 이전엔 가운데를
        addStretch(1)로만 감쌌는데, 그건 왼쪽(제목)과 오른쪽(상태+버튼들) 사이
        "남는 공간"만 절반씩 나누는 것이라 두 폭이 다르면 가운데가 창의 실제
        중앙이 아니라 한쪽으로 치우쳐 보였다. 왼쪽/오른쪽 칸을 서로 같은
        고정 폭(둘 중 더 넓은 쪽 기준)으로 맞춰야 가운데 SegmentedWidget이
        내용물 폭 차이와 무관하게 항상 창의 실제 중앙에 온다."""
        c = theme.colors()
        header = QWidget(self)
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        header.setFixedHeight(theme.HEADER_HEIGHT)
        header.setStyleSheet(f"background-color:{c['background']};")
        header_grid = QGridLayout(header)
        header_grid.setContentsMargins(
            theme.APP_CONTENT_MARGIN, 0, theme.APP_CONTENT_MARGIN, 0
        )
        header_grid.setHorizontalSpacing(theme.SPACE_4)

        # ---------- 왼쪽: 제목/부제 ----------
        left_wrap = QWidget(header)
        title_col = QVBoxLayout(left_wrap)
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(0)
        title_label = QLabel("기상 근무 모니터", left_wrap)
        title_label.setFont(theme.font(22, QFont.Weight.DemiBold))
        title_label.setStyleSheet(f"color:{c['text_primary']}; background:transparent; border:none;")
        title_col.addWidget(title_label)
        # 좁은 창(HEADER_COMPACT_BREAKPOINT 미만)에서는 부제만 숨긴다 - 제목은
        # 항상 보인다(resizeEvent -> _apply_header_compact_mode 참고).
        self._header_subtitle_label = QLabel("폭염 · 풍수해 · 제설", left_wrap)
        self._header_subtitle_label.setFont(theme.font_role("caption"))
        self._header_subtitle_label.setStyleSheet(
            f"color:{c['text_secondary']}; background:transparent; border:none;"
        )
        title_col.addWidget(self._header_subtitle_label)

        # ---------- 가운데: 화면 전환 ----------
        view_seg_wrap = QWidget(header)
        view_seg_wrap_layout = QHBoxLayout(view_seg_wrap)
        view_seg_wrap_layout.setContentsMargins(0, 0, 0, 0)
        self.view_seg = SegmentedWidget(view_seg_wrap)
        self.view_seg.addItem("detail", "지역별 상세", onClick=lambda: self._set_view_mode("detail"))
        self.view_seg.addItem("summary", "즐겨찾기 종합", onClick=lambda: self._set_view_mode("summary"))
        self.view_seg.setCurrentItem(self.view_mode)
        # 정렬 플래그 없이 addWidget()만 쓰면 QHBoxLayout이 SegmentedWidget을
        # wrap의 전체 높이까지 세로로 늘린다 - 그러면 내부 항목은 그 늘어난
        # 높이 안에서 다시 세로 중앙정렬되어 실제 y좌표가 0이 아니게 되는데,
        # qfluentwidgets의 선택 표시(흰 박스)는 SegmentedWidget 자신의 높이를
        # 기준으로 그려서 늘 위쪽에 그려지는 것처럼 보인다(실측: 늘어난
        # 상태에서 item.geometry()=y=17, 흰 박스는 y=0~30에 그려짐).
        # AlignVCenter를 주면 SegmentedWidget이 sizeHint 높이 그대로(늘어나지
        # 않고) 세로 중앙에 놓여 item.y()가 0이 되고 문제가 사라진다.
        view_seg_wrap_layout.addWidget(self.view_seg, 0, Qt.AlignmentFlag.AlignVCenter)

        # ---------- 오른쪽: 상태/새로고침/설정 ----------
        right_wrap = QWidget(header)
        right_wrap_layout = QHBoxLayout(right_wrap)
        right_wrap_layout.setContentsMargins(0, 0, 0, 0)
        right_wrap_layout.setSpacing(theme.SPACE_4)

        self.status_label = uic.StatusPill("대기", tone="neutral", parent=right_wrap)
        self.status_label.setMinimumWidth(_status_pill_min_width())
        right_wrap_layout.addWidget(self.status_label)

        refresh_btn = PushButton("새로고침", right_wrap, FluentIcon.SYNC)
        refresh_btn.setFixedHeight(theme.CONTROL_HEIGHT_DEFAULT)
        refresh_btn.setToolTip("새로고침")
        refresh_btn.setAccessibleName("새로고침")
        refresh_btn.clicked.connect(self.refresh_all)
        right_wrap_layout.addWidget(refresh_btn)

        settings_btn = uic.IconActionButton(FluentIcon.SETTING, tooltip="설정", parent=right_wrap)
        settings_btn.clicked.connect(self._open_settings)
        right_wrap_layout.addWidget(settings_btn)

        # 왼쪽/오른쪽 칸을 서로 같은 폭으로 고정(더 넓은 쪽 기준) - 부제가
        # 나중에 숨겨져도(컴팩트 모드) 이 폭은 그대로라 가운데 정렬이 안
        # 흔들린다.
        both_w = max(left_wrap.sizeHint().width(), right_wrap.sizeHint().width())
        left_wrap.setFixedWidth(both_w)
        right_wrap.setFixedWidth(both_w)

        header_grid.addWidget(left_wrap, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header_grid.addWidget(view_seg_wrap, 0, 1, Qt.AlignmentFlag.AlignCenter)
        header_grid.addWidget(
            right_wrap, 0, 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        header_grid.setColumnStretch(0, 1)
        header_grid.setColumnStretch(1, 0)
        header_grid.setColumnStretch(2, 1)

        self._header = header
        self.root_layout.addWidget(header)

        header_divider = QFrame(self)
        header_divider.setFixedHeight(1)
        header_divider.setStyleSheet(f"background-color:{c['divider']};")
        self.root_layout.addWidget(header_divider)

        self._apply_header_compact_mode(self.width())

    def _build_sidebar(self, parent):
        """평평한 split-view 왼쪽 패널: 제목 + 즐겨찾기 편집/접기 아이콘 버튼
        헤더, 그 아래 즐겨찾기 목록(비어 있으면 EmptyState). 접힘 상태에서는
        제목/편집 버튼/목록을 숨기고 접기 버튼만 좁은 레일에 남긴다 - 실제
        폭/보임 상태 적용은 _apply_sidebar_collapsed_state()가 한다(스플리터가
        준비된 뒤 _build_layout()이 그 메서드를 호출)."""
        c = theme.colors()
        sidebar = QWidget(parent)
        sidebar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sidebar.setStyleSheet(f"background-color:{c['surface']};")

        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(
            theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4
        )
        sidebar_layout.setSpacing(theme.SPACE_3)

        header_row = QHBoxLayout()
        header_row.setSpacing(theme.SPACE_2)
        self._sidebar_title_label = QLabel("즐겨찾기 지역", sidebar)
        self._sidebar_title_label.setFont(theme.font_role("card_title"))
        self._sidebar_title_label.setStyleSheet(
            f"color:{c['text_primary']}; background:transparent; border:none;"
        )
        header_row.addWidget(self._sidebar_title_label)
        header_row.addStretch(1)
        self._sidebar_edit_btn = uic.IconActionButton(FluentIcon.EDIT, tooltip="즐겨찾기 편집", parent=sidebar)
        self._sidebar_edit_btn.clicked.connect(self._open_region_manager)
        header_row.addWidget(self._sidebar_edit_btn)
        self._sidebar_collapse_btn = uic.IconActionButton(FluentIcon.LEFT_ARROW, tooltip="사이드바 접기", parent=sidebar)
        self._sidebar_collapse_btn.clicked.connect(self._toggle_sidebar_collapsed)
        header_row.addWidget(self._sidebar_collapse_btn)
        sidebar_layout.addLayout(header_row)

        self._favorites_stack = QStackedWidget(sidebar)

        self.favorites_list = ListWidget(self._favorites_stack)
        self.favorites_list.setFrameShape(QFrame.Shape.NoFrame)
        self.favorites_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.favorites_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.favorites_list.setUniformItemSizes(True)
        self.favorites_list.itemClicked.connect(self._on_favorite_item_clicked)
        self._style_favorites_list()
        self._favorites_stack.addWidget(self.favorites_list)

        self._sidebar_empty_state = uic.EmptyState(
            "즐겨찾기 지역이 없습니다",
            "편집 버튼에서 지역을 추가할 수 있습니다.",
            self._favorites_stack,
        )
        self._favorites_stack.addWidget(self._sidebar_empty_state)

        sidebar_layout.addWidget(self._favorites_stack, 1)

        self._sidebar_widget = sidebar
        return sidebar

    def _toggle_sidebar_collapsed(self):
        self._sidebar_collapsed = not getattr(self, "_sidebar_collapsed", False)
        self._apply_sidebar_collapsed_state()

    def _apply_sidebar_collapsed_state(self):
        """사이드바 접힘/펼침 상태를 실제 위젯에 반영한다. self._sidebar_collapsed는
        WeatherDutyApp 인스턴스 자체에 남아 있는 값이라(_rebuild_ui()는 위젯만
        새로 만들 뿐 self를 새로 만들지 않음), 테마 전환이나 화면 전환(view_mode)
        뒤에도 그대로 유지된다(단, 앱을 껐다 켜는 것까지 기억하진 않는다)."""
        collapsed = getattr(self, "_sidebar_collapsed", False)
        sidebar = self._sidebar_widget
        if collapsed:
            sidebar.setMinimumWidth(theme.SIDEBAR_COLLAPSED_WIDTH)
            sidebar.setMaximumWidth(theme.SIDEBAR_COLLAPSED_WIDTH)
        else:
            sidebar.setMinimumWidth(theme.SIDEBAR_MIN_WIDTH)
            sidebar.setMaximumWidth(theme.SIDEBAR_MAX_WIDTH)

        self._sidebar_title_label.setVisible(not collapsed)
        self._sidebar_edit_btn.setVisible(not collapsed)
        self._favorites_stack.setVisible(not collapsed)

        self._sidebar_collapse_btn.setIcon(FluentIcon.RIGHT_ARROW if collapsed else FluentIcon.LEFT_ARROW)
        tip = "사이드바 펼치기" if collapsed else "사이드바 접기"
        self._sidebar_collapse_btn.setToolTip(tip)
        self._sidebar_collapse_btn.setAccessibleName(tip)

        splitter = getattr(self, "_body_splitter", None)
        if splitter is not None:
            total = sum(splitter.sizes()) or self.width()
            if collapsed:
                splitter.setSizes([theme.SIDEBAR_COLLAPSED_WIDTH, max(total - theme.SIDEBAR_COLLAPSED_WIDTH, 400)])
            else:
                splitter.setSizes([theme.SIDEBAR_DEFAULT_WIDTH, max(total - theme.SIDEBAR_DEFAULT_WIDTH, 400)])

    def _style_favorites_list(self):
        c = theme.colors()
        self.favorites_list.setStyleSheet(f"""
            QListWidget {{
                background: transparent;
                border: none;
                outline: none;
            }}
            QListWidget::item {{
                padding: 0px {theme.SPACE_3}px;
                border-radius: {theme.RADIUS_CONTROL}px;
                color: {c['text_primary']};
                background: transparent;
            }}
            QListWidget::item:hover {{
                background-color: {c['surface_hover']};
            }}
            QListWidget::item:selected {{
                background-color: {c['surface_selected']};
                color: {c['text_primary']};
                font-weight: 500;
            }}
            QListWidget::item:focus {{
                border: {theme.FOCUS_RING_WIDTH}px solid {c['focus']};
            }}
        """)

    def _build_layout(self):
        c = theme.colors()
        body_container = QWidget(self)
        body_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        body_container.setStyleSheet(f"background-color:{c['background']};")
        body_layout = QVBoxLayout(body_container)
        # 헤더 좌우 여백(APP_CONTENT_MARGIN)과 맞춰 제목/사이드바 좌측 끝이
        # 수직으로 정렬되게 한다(예전에는 SPACE_4=16px라 헤더의 24px와 어긋났음).
        body_layout.setContentsMargins(
            theme.APP_CONTENT_MARGIN, theme.SPACE_4, theme.APP_CONTENT_MARGIN, theme.APP_CONTENT_MARGIN
        )
        self.root_layout.addWidget(body_container, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal, body_container)
        splitter.setHandleWidth(theme.SPLITTER_HANDLE_WIDTH)
        splitter.setChildrenCollapsible(False)
        # 손잡이는 평소엔 구분선(divider)처럼 옅게 보이다가, hover 시에만
        # accent 색으로 밝아져 "잡을 수 있는 위치"임을 알려준다.
        splitter.setStyleSheet(
            f"QSplitter::handle {{ background-color:{c['divider']}; }}"
            f"QSplitter::handle:hover {{ background-color:{c['accent']}; }}"
        )
        body_layout.addWidget(splitter)

        sidebar = self._build_sidebar(splitter)
        splitter.addWidget(sidebar)

        self.stack = QStackedWidget(splitter)
        splitter.addWidget(self.stack)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes(
            [theme.SIDEBAR_DEFAULT_WIDTH, max(self.width() - theme.SIDEBAR_DEFAULT_WIDTH, 400)]
        )
        self._body_splitter = splitter
        self._apply_sidebar_collapsed_state()

        self.detail_page = QWidget(self.stack)
        self._build_detail_widgets(self.detail_page)
        self.stack.addWidget(self.detail_page)

        self.summary_page = QWidget(self.stack)
        self._build_summary_widgets(self.summary_page)
        self.stack.addWidget(self.summary_page)

        self.stack.setCurrentWidget(self.detail_page)

    def _build_detail_widgets(self, parent):
        """지역별 상세 화면: 현재 날씨 Hero surface -> 오류/특보 상태 배너 ->
        "일별 예보" 섹션 헤더 -> 예보 행 목록(ForecastRow) 순서로 쌓는다."""
        c = theme.colors()
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_4)

        # ---------- Hero surface ----------
        hero = QFrame(parent)
        hero.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # surface 배경만으로도 background(페이지)와 구분되므로, 테두리는 빼서
        # 지역명/현재 기온을 감싸는 박스 느낌을 없앤다.
        hero.setStyleSheet(
            f"QFrame {{ background-color:{c['surface']}; border:none; border-radius:{theme.RADIUS_CARD}px; }}"
        )
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(
            theme.CARD_PADDING, theme.CARD_PADDING, theme.CARD_PADDING, theme.CARD_PADDING
        )
        hero_layout.setSpacing(theme.SPACE_5)
        layout.addWidget(hero)

        # 상단: 지역명(왼쪽, 길면 줄바꿈 + 전체 이름 tooltip) / 관측시각 배지(오른쪽)
        top_row = QHBoxLayout()
        top_row.setSpacing(theme.SPACE_3)
        self.region_name_label = QLabel("즐겨찾기 지역을 선택하세요", hero)
        self.region_name_label.setFont(theme.font_role("page_title"))
        self.region_name_label.setWordWrap(True)
        self.region_name_label.setStyleSheet(f"color:{c['text_primary']}; background:transparent; border:none;")
        self.region_name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        top_row.addWidget(self.region_name_label, 1)

        self.obs_time_label = QLabel("", hero)
        self.obs_time_label.setFont(theme.font_role("micro"))
        self.obs_time_label.setStyleSheet(
            f"color:{c['text_secondary']}; background-color:{c['surface_alt']};"
            f" border-radius:{theme.RADIUS_SMALL}px; padding:{theme.SPACE_1}px {theme.SPACE_3}px;"
        )
        top_row.addWidget(self.obs_time_label, 0, Qt.AlignmentFlag.AlignTop)
        hero_layout.addLayout(top_row)

        # 중앙: 현재 기온(왼쪽, 큰 지표) / 1시간 강수(오른쪽, 소형 지표)
        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(theme.SPACE_8)

        temp_col = QVBoxLayout()
        temp_col.setSpacing(theme.SPACE_1)
        temp_caption = QLabel("현재 기온", hero)
        temp_caption.setFont(theme.font_role("caption"))
        temp_caption.setStyleSheet(f"color:{c['text_secondary']}; background:transparent; border:none;")
        temp_col.addWidget(temp_caption)
        self.temp_label = QLabel("-℃", hero)
        self.temp_label.setFont(theme.font_role("metric_display"))
        self.temp_label.setStyleSheet(f"color:{c['text_primary']}; background:transparent; border:none;")
        temp_col.addWidget(self.temp_label)
        metrics_row.addLayout(temp_col)

        rain_col = QVBoxLayout()
        rain_col.setSpacing(theme.SPACE_1)
        rain_caption = QLabel("1시간 강수", hero)
        rain_caption.setFont(theme.font_role("caption"))
        rain_caption.setStyleSheet(f"color:{c['text_secondary']}; background:transparent; border:none;")
        rain_col.addWidget(rain_caption)
        self.rain_label = QLabel("-mm", hero)
        self.rain_label.setFont(theme.font(22, QFont.Weight.DemiBold))
        self.rain_label.setStyleSheet(f"color:{c['text_primary']}; background:transparent; border:none;")
        rain_col.addWidget(self.rain_label)
        metrics_row.addLayout(rain_col)

        metrics_row.addStretch(1)
        hero_layout.addLayout(metrics_row)

        # 오류 배너(danger, 오류 없으면 숨김) - InlineBanner(제목 포함)로 통합.
        # self.error_label은 기존 코드 호환을 위한 alias(본문 QLabel 그대로).
        self._error_banner_frame = uic.InlineBanner(
            "", title="데이터 조회 오류", level="danger", parent=hero,
        )
        hero_layout.addWidget(self._error_banner_frame)
        self._error_banner_frame.setVisible(False)
        self.error_label = self._error_banner_frame.text_label

        # 특보 배너 - 특보 없음(평상시)은 subtle=True로 눈에 띄지 않게,
        # 특보 있음일 때만 danger 톤으로 강하게 표시한다(_style_warning_banner).
        # self.warning_banner도 기존 코드 호환을 위한 alias.
        self._warning_banner_frame = uic.InlineBanner(
            "현재 발효 중인 특보가 없습니다.", level="success", subtle=True, parent=hero,
        )
        hero_layout.addWidget(self._warning_banner_frame)
        self.warning_banner = self._warning_banner_frame.text_label

        # ---------- 일별 예보 ----------
        forecast_header = uic.SectionHeader(
            "일별 예보",
            subtitle="지난 실측 2일 + 향후 예보 (가져올 수 있는 최대 기간)",
            parent=parent,
        )
        layout.addWidget(forecast_header)

        self.forecast_scroll = ScrollArea(parent)
        self.forecast_scroll.setWidgetResizable(True)
        forecast_card = QFrame(parent)
        forecast_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        forecast_card.setStyleSheet(
            f"QFrame {{ background-color:{c['surface']}; border:1px solid {c['border_subtle']};"
            f" border-radius:{theme.RADIUS_CARD}px; }}"
        )
        self.forecast_layout = QVBoxLayout(forecast_card)
        self.forecast_layout.setContentsMargins(0, theme.SPACE_2, 0, theme.SPACE_2)
        self.forecast_layout.setSpacing(0)
        self.forecast_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.forecast_scroll.setWidget(forecast_card)
        self.forecast_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        layout.addWidget(self.forecast_scroll, 1)

    def _style_warning_banner(self, has_warning):
        """특보 배너 톤 갱신. 특보가 있을 때만 danger로 강하게(subtle=False),
        없으면 success·subtle=True로 조용하게(초록을 과하게 쓰지 않는다)."""
        if has_warning:
            self._warning_banner_frame.set_level("danger", subtle=False)
        else:
            self._warning_banner_frame.set_level("success", subtle=True)

    def _build_summary_widgets(self, parent):
        """즐겨찾기 종합보기: 제목/지사 관리 버튼 -> 가로 스크롤 날짜 선택 ->
        (지사 미설정/일부 오류 안내 배너, 평소엔 숨김) -> 종합표(또는 빈 상태)."""
        c = theme.colors()
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_4)

        # ---------- 상단: 제목(좌) + 지사 관리 버튼(우) ----------
        branch_btn = PushButton("지사 관리", parent, FluentIcon.PEOPLE)
        branch_btn.setToolTip("지사 관리")
        branch_btn.setAccessibleName("지사 관리")
        branch_btn.clicked.connect(self._open_branch_manager)
        summary_header = uic.SectionHeader(
            "지사별 종합 현황",
            subtitle="지사명을 클릭하면 날짜·시간대별 누적강수량을 관할 지역별로 비교할 수 있습니다.",
            action_widget=branch_btn,
            parent=parent,
        )
        layout.addWidget(summary_header)

        # ---------- 날짜 선택: 가로 스크롤 컨테이너 안에 기존 SegmentedWidget 배치 ----------
        # (날짜가 많아져도 항목이 압축되지 않게 - SegmentedWidget 자체 로직 등은
        # 그대로 두고, 담는 컨테이너만 가로 스크롤 가능하게 바꾼다)
        date_bar = QFrame(parent)
        date_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        date_bar.setStyleSheet(
            f"QFrame {{ background-color:{c['surface']}; border:1px solid {c['border_subtle']};"
            f" border-radius:{theme.RADIUS_PANEL}px; }}"
        )
        date_bar_layout = QHBoxLayout(date_bar)
        date_bar_layout.setContentsMargins(theme.SPACE_4, theme.SPACE_2, theme.SPACE_4, theme.SPACE_2)
        date_bar_layout.setSpacing(theme.SPACE_3)
        date_hdr = QLabel("날짜", date_bar)
        date_hdr.setFont(theme.font_role("label"))
        date_hdr.setStyleSheet(f"color:{c['text_secondary']}; background:transparent; border:none;")
        date_bar_layout.addWidget(date_hdr)

        self.summary_date_selector = SegmentedWidget(date_bar)
        self.summary_date_selector.setStyleSheet("background:transparent; border:none;")
        date_scroll = SingleDirectionScrollArea(date_bar, orient=Qt.Orientation.Horizontal)
        date_scroll.setWidget(self.summary_date_selector)
        date_scroll.setWidgetResizable(True)
        date_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        date_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        date_scroll.setFixedHeight(theme.CONTROL_HEIGHT_LARGE)
        # summary_date_selector는 자연 높이(sizeHint)로 고정되므로(아래
        # _update_summary_date_selector에서 setMaximumHeight), 이 44px
        # 뷰포트보다 낮아진 만큼 세로로 중앙 정렬한다.
        date_scroll.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        date_scroll.setStyleSheet("QScrollArea { border:none; background:transparent; }")
        date_bar_layout.addWidget(date_scroll, 1)
        layout.addWidget(date_bar)

        # ---------- 비차단 안내 배너: 지사 미설정 / 일부 오류(평소엔 숨김) ----------
        self._summary_no_branch_banner = uic.InlineBanner(
            "등록된 지사가 없어 전체 지역이 \"미분류\"로 표시됩니다. 지사 관리에서 지사를 추가할 수 있습니다.",
            level="info", parent=parent,
        )
        self._summary_no_branch_banner.setVisible(False)
        layout.addWidget(self._summary_no_branch_banner)

        # 기본 문구/톤은 "일부 실패"(warning) 기준으로 만들어 두고, 실제
        # 렌더링에서 전체 실패로 판단되면 danger로 바꿔 문구도 함께 갱신한다.
        self._summary_error_banner = uic.InlineBanner(
            "일부 지역의 데이터를 불러오지 못했습니다. 지역별 상세보기에서 자세한 오류를 확인할 수 있습니다.",
            level="warning", parent=parent,
        )
        self._summary_error_banner.setVisible(False)
        layout.addWidget(self._summary_error_banner)

        # ---------- 종합표 / 빈 상태 ----------
        # self.summary_table 자체는 항상 존재해야 하므로(요구 속성), 위젯을
        # 갈아끼우지 않고 QStackedWidget으로 표와 빈 상태 사이만 전환한다.
        self._summary_content_stack = QStackedWidget(parent)

        self.summary_table = TableWidget(self._summary_content_stack)
        self.summary_table.setColumnCount(7)
        # "체감 최저/최고"·"강수량(00~24시 누적)" 전체 문구를 헤더에 그대로 쓰면 그
        # 열만 지나치게 넓어져 좁은 화면에서 지역명 열이 짓눌린다(960px에서 실측)
        # - 헤더는 짧게 쓰고 전체 의미는 툴팁으로 보완한다(데이터·정렬 기준은 그대로).
        self.summary_table.setHorizontalHeaderLabels(
            ["지사", "지역", "최저/최고", "체감", "강수확률", "강수량", "특보"]
        )
        self.summary_table.horizontalHeaderItem(3).setToolTip("체감 최저/최고")
        self.summary_table.horizontalHeaderItem(5).setToolTip("강수량 (00~24시 누적)")
        self.summary_table.verticalHeader().hide()
        self.summary_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.summary_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.summary_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.summary_table.setBorderRadius(theme.RADIUS_CARD)
        self.summary_table.verticalHeader().setDefaultSectionSize(theme.TABLE_ROW_HEIGHT)
        self.summary_table.horizontalHeader().setFixedHeight(theme.TABLE_HEADER_HEIGHT)
        self.summary_table.horizontalHeader().setStretchLastSection(False)
        # 기본 word wrap(true)이 켜진 채로 셀 폭이 좁으면 긴 지사명이 여러 줄로
        # 쪼개져 행 높이를 넘치는데, elide는 word wrap이 꺼져 있어야 적용되므로
        # 반드시 함께 꺼서 "한 줄 + ... + 툴팁"으로만 넘치게 한다.
        self.summary_table.setWordWrap(False)
        self.summary_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.summary_table.cellDoubleClicked.connect(self._on_summary_cell_double_clicked)
        self.summary_table.cellClicked.connect(self._on_summary_cell_clicked)
        # 지사명 칸에 키보드로 초점을 옮긴 뒤 Enter/Return을 눌러도 마우스
        # 클릭과 같은 동작(_open_branch_range)이 나가도록 - activated는
        # Qt에서 "Enter/Return 또는 더블클릭으로 항목을 활성화"할 때 공통으로
        # 나가는 시그널이라 별도 keyPressEvent 오버라이드 없이 재사용한다.
        self.summary_table.cellActivated.connect(self._on_summary_cell_clicked)
        self._style_summary_table_header()

        # resizeColumnsToContents() 한 번으로 퉁치지 않고, 열 성격에 맞게 각각
        # 정책을 명시한다 - 지사/강수량은 span·긴 문구 때문에 내용 기준 자동
        # 계산이 부정확해질 수 있어 Interactive+초기폭으로, 지역명만 남는 폭을
        # 가져가도록 Stretch, 나머지 숫자열은 ResizeToContents로 짧게 맞춘다.
        header = self.summary_table.horizontalHeader()
        # Stretch 열(지역)은 다른 열들의 폭 합이 뷰포트를 넘으면 0까지 눌릴 수 있어
        # (960px 좁은 화면에서 지역명이 통째로 사라지는 문제로 실측됨),
        # 모든 열에 최소 폭을 강제해 그 이하로는 좁아지지 않고 가로 스크롤로 넘어가게 한다.
        header.setMinimumSectionSize(64)
        # 폭을 먼저 잡아두고 나서 Stretch를 걸어야 두 Stretch 열(지역/강수량)이
        # 남는 공간을 이 비율로 나눠 가진다 - 순서가 바뀌면 지역 열 혼자 남는
        # 공간을 전부 가져가 강수량 열이 넓은 화면에서도 계속 좁게 남아
        # "★ 65mm(15시 최대)" 같은 문구가 잘리는 문제가 있었다.
        self.summary_table.setColumnWidth(0, 100)
        self.summary_table.setColumnWidth(1, 220)
        self.summary_table.setColumnWidth(5, 160)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self._summary_content_stack.addWidget(self.summary_table)

        self._summary_empty_state = uic.EmptyState("표시할 데이터가 없습니다", "", self._summary_content_stack)
        self._summary_content_stack.addWidget(self._summary_empty_state)

        self._summary_loading_state = uic.LoadingState(
            "기상 정보를 조회하고 있습니다.", self._summary_content_stack,
        )
        self._summary_content_stack.addWidget(self._summary_loading_state)

        layout.addWidget(self._summary_content_stack, 1)

    def _style_summary_table_header(self):
        c = theme.colors()
        header = self.summary_table.horizontalHeader()
        header.setFont(theme.font_role("label"))
        header.setStyleSheet(
            f"QHeaderView::section {{ background-color:{c['surface_alt']}; color:{c['text_primary']};"
            f" border:none; padding:0 {theme.SPACE_3}px; }}"
        )

    def _show_summary_empty_state(self, title, description, tone="neutral", action_widget=None):
        self._summary_empty_state.set_title(title)
        self._summary_empty_state.set_description(description)
        self._summary_empty_state.set_tone(tone)
        self._summary_empty_state.set_action_widget(action_widget)
        self._summary_content_stack.setCurrentWidget(self._summary_empty_state)

    def _show_summary_loading(self):
        self._summary_content_stack.setCurrentWidget(self._summary_loading_state)

    def _show_summary_table(self):
        self._summary_content_stack.setCurrentWidget(self.summary_table)

    # ---------- view mode ----------
    def _sync_view_mode_widgets(self):
        """self.view_mode에 맞춰 스택 페이지와 세그먼트 선택 상태를 맞춘다.
        _build_layout()은 항상 상세보기 페이지로 스택을 초기화하므로,
        팔레트가 바뀌어 _rebuild_ui()가 레이아웃을 통째로 다시 만든 뒤에도
        이걸 호출해 이전 view_mode(종합보기 등)를 복원해야 한다."""
        if self.view_mode == "summary":
            self.stack.setCurrentWidget(self.summary_page)
        else:
            self.stack.setCurrentWidget(self.detail_page)
        self.view_seg.setCurrentItem(self.view_mode)

    def _set_view_mode(self, mode):
        if self.view_mode == mode:
            return
        self.view_mode = mode
        self._sync_view_mode_widgets()
        self._refresh_current_view()

    def _on_summary_date_selected(self, date_str):
        self.selected_summary_date = date_str
        self._render_summary(config.get_favorites())

    def _refresh_current_view(self):
        favorites = config.get_favorites()
        self._render_favorite_list(favorites)
        if self.view_mode == "summary":
            self._render_summary(favorites)
        elif self.selected_region:
            self._render_region(self.selected_region)
        else:
            self._render_no_region_selected()

    # ---------- dialogs ----------
    def _open_region_manager(self):
        RegionManagerDialog(self, self._on_favorite_changed).exec()

    def _open_branch_manager(self):
        BranchManagerDialog(self, self._refresh_current_view).exec()

    def _open_settings(self):
        SettingsDialog(self, self.refresh_all).exec()

    def _on_favorite_changed(self, added=None, removed=None):
        favorites = config.get_favorites()
        if removed and self.selected_region == removed:
            self.selected_region = favorites[0] if favorites else None
        if added and self.selected_region is None:
            self.selected_region = added
        if removed:
            self.reports.pop(removed, None)
        self._refresh_current_view()

        service_key = config.get_service_key()
        if added and service_key:
            threading.Thread(target=self._fetch_one, args=(service_key, added), daemon=True).start()

    # ---------- data: full refresh ----------
    def refresh_all(self):
        service_key = config.get_service_key()
        if not service_key:
            self.status_label.set_state(text="서비스키 필요", tone="warning")
            self.reports = {}
            self._refresh_current_view()
            return

        favorites = config.get_favorites()
        self.status_label.set_state(text="조회 중", tone="info")
        self._fetch_seq += 1
        seq = self._fetch_seq
        for name in favorites:
            self.reports.pop(name, None)
        self._refresh_current_view()

        threading.Thread(target=self._fetch_all, args=(service_key, favorites, seq), daemon=True).start()

    def _fetch_all(self, service_key, favorites, seq):
        all_regions = regions.all_regions()
        # getWthrWrnMsg는 stnId가 지방기상청 관할 코드라, 즐겨찾기가 걸쳐 있는
        # 관할 구역마다 따로 조회해야 한다(하나로 퉁치면 다른 지방청 관할 지역의
        # 특보가 누락됨) - 같은 관할을 공유하는 지역끼리는 조회 결과를 재사용한다.
        needed_stn_ids = {
            all_regions[name]["warn_stn_id"] for name in favorites
            if name in all_regions and all_regions[name].get("warn_stn_id")
        }
        warnings_by_zone = {}
        warnings_error = None
        for stn_id in needed_stn_ids:
            try:
                warnings_by_zone[stn_id] = kma_client.get_active_warnings(service_key, stn_id)
            except Exception as exc:  # noqa: BLE001
                warnings_by_zone[stn_id] = []
                warnings_error = str(exc)

        reports = {}
        for name in favorites:
            info = all_regions.get(name)
            if not info:
                continue
            zone_warnings = warnings_by_zone.get(info.get("warn_stn_id"), [])
            report = kma_client.build_region_report(service_key, name, info, zone_warnings)
            if warnings_error:
                report["errors"].append(f"특보 조회 실패: {warnings_error}")
            reports[name] = report

        self._bridge.all_done.emit(seq, reports, favorites)

    def _apply_fetch_result(self, seq, reports, favorites):
        if seq != self._fetch_seq:
            return  # 새 새로고침이 이미 시작돼 이 결과는 낡은 것 -> 버린다
        has_errors = any(report.get("errors") for report in reports.values())
        if has_errors:
            self.status_label.set_state(text="일부 오류", tone="warning")
        else:
            self.status_label.set_state(text="갱신 완료", tone="success")
        self.reports.update(reports)
        if favorites and (self.selected_region not in self.reports):
            self.selected_region = favorites[0]
        self._refresh_current_view()

    # ---------- data: single-region fetch (즐겨찾기에 지역 추가 시) ----------
    def _fetch_one(self, service_key, name):
        info = regions.all_regions().get(name)
        if not info:
            return
        try:
            warnings = kma_client.get_active_warnings(service_key, info.get("warn_stn_id"))
        except Exception:  # noqa: BLE001
            warnings = []
        report = kma_client.build_region_report(service_key, name, info, warnings)
        self._bridge.one_done.emit(name, report)

    def _merge_one_report(self, name, report):
        self.reports[name] = report
        self._refresh_current_view()

    # ---------- rendering: sidebar ----------
    def _render_favorite_list(self, favorites):
        c = theme.colors()
        self.favorites_list.clear()

        if not favorites:
            self._favorites_stack.setCurrentWidget(self._sidebar_empty_state)
            return
        self._favorites_stack.setCurrentWidget(self.favorites_list)

        for name in favorites:
            is_loading = name not in self.reports
            # 텍스트는 지역명 그대로 두고("조회 중… " 접두어 없음), 진행 상태는
            # 아이콘 점 하나로만 곁들인다 - UserRole도 그대로 지역명을 담는다.
            # 단, 점 색깔만으로 상태를 전달하지 않도록 tooltip에는 "조회 중"
            # 문구를 함께 넣는다(색맹 등으로 색을 구분 못 해도 상태를 알 수 있게).
            item = QListWidgetItem(name)
            item.setFont(self.font_body)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip(f"{name} (조회 중)" if is_loading else name)
            item.setSizeHint(QSize(0, 40))
            item.setIcon(_dot_icon(c["info"]) if is_loading else QIcon())
            self.favorites_list.addItem(item)
            if name == self.selected_region:
                self.favorites_list.setCurrentItem(item)

    def _on_favorite_item_clicked(self, item):
        name = item.data(Qt.ItemDataRole.UserRole)
        if name:
            self._select_region(name)

    def _select_region(self, name):
        self.selected_region = name
        if self.view_mode != "detail":
            self._set_view_mode("detail")
        else:
            self._refresh_current_view()

    # ---------- rendering: detail view ----------
    def _render_region(self, name):
        self.region_name_label.setText(name)
        self.region_name_label.setToolTip(name)
        report = self.reports.get(name)
        if not report:
            # 이전에 선택했던 지역의 예보/오류/특보가 남아있지 않도록 비우고,
            # "서비스키 미설정"과 "조회 중"을 구분해서 안내한다.
            self.temp_label.setText("-℃")
            self.rain_label.setText("-mm")
            self.obs_time_label.setText("")
            self._error_banner_frame.setVisible(False)
            self._warning_banner_frame.setVisible(False)
            if not config.get_service_key():
                self._render_forecast_service_key_missing()
            else:
                self._render_forecast_loading(name)
            return

        self._warning_banner_frame.setVisible(True)
        current = report.get("current") or {}
        temp = current.get("temp")
        rain = current.get("rain_1h")
        obs_time = current.get("obs_time", "-")

        self.region_name_label.setText(name)
        self.region_name_label.setToolTip(name)
        self.temp_label.setText(f"{temp}℃" if temp is not None else "-℃")
        self.rain_label.setText(f"{rain}mm" if rain is not None else "-mm")
        self.obs_time_label.setText(f"관측 {obs_time}")

        errors = report.get("errors") or []
        self.error_label.setText("\n".join(errors))
        self._error_banner_frame.setVisible(bool(errors))

        warnings = report.get("warnings") or []
        if warnings:
            self.warning_banner.setText("\n".join(warnings))
        else:
            self.warning_banner.setText("현재 발효 중인 특보가 없습니다.  (당일 기준, 향후 예정일은 표시되지 않음)")
        self._style_warning_banner(has_warning=bool(warnings))

        self._render_forecast(name, report.get("forecast", []))

    def _render_no_region_selected(self):
        """즐겨찾기가 하나도 없어 선택된 지역이 없는 상태 - 이전에 봤던 지역의
        예보가 화면에 남아 있지 않도록 Hero/배너/예보 영역을 모두 비운다."""
        self.region_name_label.setText("즐겨찾기 지역을 선택하세요")
        self.region_name_label.setToolTip("")
        self.temp_label.setText("-℃")
        self.rain_label.setText("-mm")
        self.obs_time_label.setText("")
        self._error_banner_frame.setVisible(False)
        self._warning_banner_frame.setVisible(False)
        _clear_layout(self.forecast_layout)
        parent_widget = self.forecast_scroll.widget()
        empty = uic.EmptyState(
            "즐겨찾기 지역이 없습니다",
            "왼쪽 즐겨찾기 편집에서 지역을 추가하면 예보를 볼 수 있습니다.",
            parent_widget,
        )
        self.forecast_layout.addWidget(empty)

    def _render_forecast_loading(self, region_name):
        _clear_layout(self.forecast_layout)
        parent_widget = self.forecast_scroll.widget()
        loading = uic.LoadingState(f"{region_name} 날씨 정보를 조회하고 있습니다.", parent_widget)
        self.forecast_layout.addWidget(loading)

    def _render_forecast_service_key_missing(self):
        _clear_layout(self.forecast_layout)
        parent_widget = self.forecast_scroll.widget()
        open_settings_btn = PrimaryPushButton("설정 열기", parent_widget)
        open_settings_btn.clicked.connect(self._open_settings)
        empty = uic.EmptyState(
            "서비스키 설정이 필요합니다.",
            "설정에서 기상청 API 서비스키를 등록하면 날씨 정보를 조회할 수 있습니다.",
            parent_widget, tone="warning", action_widget=open_settings_btn,
        )
        self.forecast_layout.addWidget(empty)

    def _render_forecast(self, region_name, days):
        _clear_layout(self.forecast_layout)
        parent_widget = self.forecast_scroll.widget()

        if not days:
            empty = uic.EmptyState(
                "표시할 예보 데이터가 없습니다.",
                "새로고침 버튼을 눌러 다시 시도해 보세요.",
                parent_widget,
            )
            self.forecast_layout.addWidget(empty)
            return

        c = theme.colors()
        today_str = datetime.date.today().strftime("%Y%m%d")
        for day in days:
            row = uic.ForecastRow(parent_widget)

            pop = day.get("pop")
            fl_min, fl_max = day.get("feels_like_min"), day.get("feels_like_max")
            tmin, tmax = day.get("tmin"), day.get("tmax")
            temp_text = _format_min_max(tmin, tmax)

            has_detail = bool(day.get("hourly"))
            row.set_data(
                date_text=_pretty_date_with_weekday(day.get("date") or "", today_str),
                condition_text=day.get("condition") or "-",
                pop_text=(f"강수 {pop}%" if pop is not None else "강수 -"),
                pop_tone=_pop_tone(pop),
                pcp_text=_pcp_display_text(day),
                pcp_tooltip=_pcp_display_tooltip(day),
                feels_text=(f"체감 {_format_min_max(fl_min, fl_max)}" if fl_min is not None else ""),
                source_text=day.get("source") or "-",
                source_tone=("info" if day.get("source") == "실측" else "neutral"),
                temp_text=temp_text,
                tooltip=_forecast_row_tooltip(day),
                has_detail=has_detail,
                disabled_reason=("" if has_detail else _hourly_detail_reason(day)),
            )
            # 더블클릭(기존 동작)과 상세보기 버튼/키보드 활성화(activated, 신규)는
            # ForecastRow 내부에서 서로 다른 사용자 동작에만 배타적으로 연결되어
            # 있어(더블클릭은 항상, activated는 has_detail일 때만) 같은 다이얼로그를
            # 열어도 한 번의 조작에 중복 호출되지 않는다.
            row.doubleClicked.connect(lambda n=region_name, d=day: self._open_hourly_detail(n, d))
            row.activated.connect(lambda n=region_name, d=day: self._open_hourly_detail(n, d))
            self.forecast_layout.addWidget(row)

            separator = QFrame(parent_widget)
            separator.setFixedHeight(1)
            separator.setStyleSheet(f"background-color:{c['divider']};")
            self.forecast_layout.addWidget(separator)

    def _open_hourly_detail(self, region_name, day):
        HourlyDetailDialog(self, region_name, day).exec()

    def _open_branch_range(self, branch_name, members):
        BranchRangeDialog(self, branch_name, members, self.reports).exec()

    # ---------- rendering: summary view (지사별로 묶어 날짜 하나를 골라 비교) ----------
    def _all_summary_dates(self, favorites):
        all_dates = []
        seen = set()
        for name in favorites:
            report = self.reports.get(name)
            if not report:
                continue
            for day in report.get("forecast", []):
                d = day.get("date")
                if d and d not in seen:
                    seen.add(d)
                    all_dates.append(d)
        all_dates.sort()
        return all_dates

    def _update_summary_date_selector(self, all_dates):
        if not all_dates:
            self.summary_date_selector.clear()
            self._summary_date_selector_dates = []
            return

        today_str = datetime.datetime.now().strftime("%Y%m%d")
        if self.selected_summary_date not in all_dates:
            # 지난 실측 날짜가 목록 맨 앞에 추가되므로, 처음 열 때는 과거 날짜가 아니라
            # 오늘(또는 오늘이 없으면 가장 빠른 미래 날짜)을 기본으로 보여준다.
            self.selected_summary_date = next((d for d in all_dates if d >= today_str), all_dates[0])

        # 날짜 목록 자체가 안 바뀌었으면(가장 흔한 경우 - 날짜 칩만 클릭) 위젯을
        # 통째로 지우고 다시 만들지 않는다. 매번 clear()+재생성하면 새로 만든
        # 항목의 레이아웃 지오메트리가 아직 확정되지 않은 상태에서
        # setCurrentItem()이 실행되어, 선택 표시(흰 박스)가 애니메이션 목표
        # 위치를 잘못 계산해 이전 위치에 멈춰 있는 것처럼 보이는 문제가 있었다.
        if all_dates == getattr(self, "_summary_date_selector_dates", None):
            self.summary_date_selector.setCurrentItem(self.selected_summary_date)
            return

        self.summary_date_selector.clear()
        for date_str in all_dates:
            # routeKey(date_str)는 그대로 두고 표시 문구만 "오늘 08/28" 형태로.
            chip_text = _summary_date_chip_text(date_str, today_str)
            self.summary_date_selector.addItem(
                date_str, chip_text, onClick=lambda _c=False, d=date_str: self._on_summary_date_selected(d)
            )
        self._summary_date_selector_dates = list(all_dates)
        # SingleDirectionScrollArea가 setWidgetResizable(True)로 이 위젯을
        # 스크롤 뷰포트 높이(44px)까지 늘리면, 내부 항목이 그 늘어난 높이
        # 안에서 다시 세로 중앙정렬되어 y좌표가 0이 아니게 되는데
        # qfluentwidgets의 선택 표시(흰 박스)는 위젯 자신의 높이 기준(y=0)
        # 으로 그려서 어긋나 보인다 - 자연 높이로 최대 높이를 고정해 늘어나지
        # 않게 하고, 대신 스크롤 영역 쪽(_build_summary_widgets)에서 세로
        # 중앙 정렬한다.
        natural_height = self.summary_date_selector.sizeHint().height()
        if natural_height > 0:
            self.summary_date_selector.setMaximumHeight(natural_height)
        self.summary_date_selector.setCurrentItem(self.selected_summary_date)

    def _render_summary(self, favorites):
        c = theme.colors()
        table = self.summary_table
        table.setRowCount(0)
        self._summary_row_days = {}
        self._summary_branch_rows = {}
        # 빈 상태로 빠지는 경우에도 이전 렌더링에서 켜졌던 배너가 그대로 남지
        # 않도록, 매 렌더링마다 우선 둘 다 끈 뒤 필요할 때만 다시 켠다.
        self._summary_no_branch_banner.setVisible(False)
        self._summary_error_banner.setVisible(False)

        if not favorites:
            self._show_summary_empty_state(
                "종합보기에 표시할 즐겨찾기 지역이 없습니다.",
                "즐겨찾기 편집에서 지역을 추가해 주세요.",
            )
            return

        if not config.get_service_key():
            open_settings_btn = PrimaryPushButton("설정 열기", self._summary_content_stack)
            open_settings_btn.clicked.connect(self._open_settings)
            self._show_summary_empty_state(
                "서비스키 설정이 필요합니다.",
                "설정에서 기상청 API 서비스키를 등록하면 종합 현황을 볼 수 있습니다.",
                tone="warning", action_widget=open_settings_btn,
            )
            return

        all_dates = self._all_summary_dates(favorites)
        self._update_summary_date_selector(all_dates)

        if not all_dates:
            # 서비스키는 있지만 즐겨찾기 중 아직 응답을 못 받은 게 있으면
            # "조회 중", 전부 응답은 왔는데 예보 날짜가 없으면 진짜 "데이터
            # 없음"으로 구분한다(새 네트워크 재시도 로직을 만들지 않고,
            # 이미 갖고 있는 self.reports 상태만으로 구분).
            if any(self.reports.get(r) is None for r in favorites):
                self._show_summary_loading()
            else:
                self._show_summary_empty_state(
                    "표시할 데이터가 없습니다.",
                    "예보 데이터가 없습니다. 새로고침 버튼으로 다시 시도해 주세요.",
                )
            return

        self._show_summary_table()
        target_date = self.selected_summary_date

        branches = config.get_branches()
        assigned = set()
        groups = []
        for branch_name in sorted(branches):
            members = [r for r in branches[branch_name] if r in favorites]
            if members:
                groups.append((branch_name, members))
                assigned.update(members)
        unassigned = [r for r in favorites if r not in assigned]
        if unassigned:
            groups.append(("미분류", unassigned))

        # 지사 미설정/일부 오류는 표를 막지 않는 비차단 안내(InlineBanner)로만 알린다.
        self._summary_no_branch_banner.setVisible(not branches)
        error_regions = [r for r in favorites if (self.reports.get(r) or {}).get("errors")]
        if error_regions:
            # 일부만 실패하면 warning, 즐겨찾기 전체가 실패하면 danger로
            # 구분한다(강수확률과 달리 이건 실제 조회 실패이므로 danger 자체는
            # 유지하되 "일부"와 "전체"를 다른 톤으로 알린다).
            if len(error_regions) == len(favorites):
                self._summary_error_banner.set_message(
                    "즐겨찾기 지역의 데이터를 모두 불러오지 못했습니다. 서비스키와 네트워크 연결을 확인해 주세요.",
                    level="danger",
                )
            else:
                self._summary_error_banner.set_message(
                    "일부 지역의 데이터를 불러오지 못했습니다. 지역별 상세보기에서 자세한 오류를 확인할 수 있습니다.",
                    level="warning",
                )
            self._summary_error_banner.setVisible(True)
        else:
            self._summary_error_banner.setVisible(False)

        total_rows = sum(len(members) for _b, members in groups)
        table.setRowCount(total_rows)

        row_idx = 0
        for branch_name, members in groups:
            start_row = row_idx

            member_days = {}
            best_name, best_amount = None, -1.0
            for region_name in members:
                report = self.reports.get(region_name)
                day = None
                if report:
                    day = next((d for d in report.get("forecast", []) if d.get("date") == target_date), None)
                member_days[region_name] = day
                if day:
                    amount = _pcp_numeric(day.get("pcp"))
                    if amount > best_amount:
                        best_amount = amount
                        best_name = region_name

            for region_name in members:
                report = self.reports.get(region_name)
                day = member_days[region_name]
                is_loading = report is None
                # 최다 강수는 특보·오류가 아니므로 행 전체를 강한 색으로 칠하지 않는다 -
                # 강수량 셀 배경(accent_soft)+★ 표시+글자 굵기만으로 구분한다.
                is_best = region_name == best_name and best_amount > 0
                row_bg = c["surface"]

                self._summary_row_days[row_idx] = (region_name, day)

                # 지역명 앞에 "조회 중… " 문구를 붙이는 대신, 로딩 중임을
                # 나타내는 작은 점 글리프(색이 아니라 기호 자체로 구분)와
                # tooltip으로만 전달해 지역명 자체는 항상 그대로 보이게 한다.
                if is_loading:
                    name_text = f"● {region_name}"
                    name_tooltip = f"{region_name} 데이터를 조회하고 있습니다."
                else:
                    name_text = region_name
                    name_tooltip = region_name
                self._set_summary_item(
                    table, row_idx, 1, name_text, c["text_primary"], row_bg, theme.font_role("body"),
                    align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, tooltip=name_tooltip,
                )

                tmin, tmax = (day.get("tmin"), day.get("tmax")) if day else (None, None)
                temp_text = _format_min_max(tmin, tmax)
                self._set_summary_item(
                    table, row_idx, 2, temp_text, c["text_primary"], row_bg, theme.font_role("caption"),
                    align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                )

                fl_min, fl_max = (day.get("feels_like_min"), day.get("feels_like_max")) if day else (None, None)
                feels_tooltip = ""
                if fl_min is not None:
                    feels_text = _format_min_max(fl_min, fl_max)
                elif day and day.get("source") == "중기예보":
                    # 출처 배지가 이미 "중기예보"를 보여주므로 값 칸에서는
                    # 반복하지 않고 "—" + 이유를 담은 tooltip만 남긴다.
                    feels_text = "—"
                    feels_tooltip = "중기예보는 체감온도를 제공하지 않습니다."
                else:
                    feels_text = "—"
                self._set_summary_item(
                    table, row_idx, 3, feels_text, c["text_secondary"], row_bg, theme.font_role("caption"),
                    align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, tooltip=feels_tooltip,
                )

                pop = day.get("pop") if day else None
                pop_text = f"{pop}%" if pop is not None else "—"
                self._set_summary_item(
                    table, row_idx, 4, pop_text, theme.pop_color(pop, c), row_bg, theme.font_role("caption"),
                    align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                )

                pcp_tooltip = ""
                if day is None:
                    pcp_text = "—"
                elif day.get("pcp"):
                    peak = _pcp_peak_hour_text(day)
                    pcp_text = f"{day.get('pcp')}{peak}" if peak else day.get("pcp")
                elif day.get("source") == "중기예보":
                    # 출처 배지(특보 열 옆이 아니라 지사 클릭 시 비교창 등에서
                    # 이미 "중기예보"를 보여주므로) 값 칸에서는 반복하지 않고
                    # "—" + tooltip으로만 이유를 설명한다.
                    pcp_text = "—"
                    pcp_tooltip = "중기예보는 강수량을 제공하지 않습니다."
                else:
                    pcp_text = "강수없음"
                pcp_display = f"★ {pcp_text}" if is_best else pcp_text
                pcp_bg = c["accent_soft"] if is_best else row_bg
                pcp_font_role = "label" if is_best else "caption"  # label=Medium 굵기로 강조
                self._set_summary_item(
                    table, row_idx, 5, pcp_display, c["text_primary"], pcp_bg, theme.font_role(pcp_font_role),
                    align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, tooltip=pcp_tooltip,
                )

                warnings_list = (report.get("warnings") or []) if report else []
                if warnings_list:
                    warn_text = "⚠ 특보"
                    warn_fg, warn_bg_cell = c["danger"], c["danger_soft"]
                    warn_tooltip = "\n".join(warnings_list)
                else:
                    warn_text = "—"
                    warn_fg, warn_bg_cell = c["text_tertiary"], row_bg
                    warn_tooltip = ""
                self._set_summary_item(
                    table, row_idx, 6, warn_text, warn_fg, warn_bg_cell, theme.font_role("caption"),
                    align=Qt.AlignmentFlag.AlignCenter, tooltip=warn_tooltip,
                )

                self._set_summary_item(
                    table, row_idx, 0, "", c["text_primary"], c["surface_alt"], theme.font_role("body_medium"),
                    align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                )

                row_idx += 1

            # 지사명 클릭 = 시간대별 누적강수 비교(_open_branch_range)라는 걸 색상 없이도
            # 알 수 있도록 chevron 문구 + 툴팁을 함께 붙인다.
            branch_item = QTableWidgetItem(f"{branch_name}  ›")
            branch_item.setForeground(_qcolor(c["text_primary"]))
            branch_item.setBackground(_qcolor(c["surface_alt"]))
            branch_item.setFont(theme.font_role("body_medium"))
            branch_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            branch_item.setToolTip("클릭하여 시간대별 누적강수 비교")
            table.setItem(start_row, 0, branch_item)
            if row_idx - start_row > 1:
                table.setSpan(start_row, 0, row_idx - start_row, 1)
            for r in range(start_row, row_idx):
                self._summary_branch_rows[r] = (branch_name, list(members))

    @staticmethod
    def _set_summary_item(table, row, col, text, color_hex, bg_hex, font, align=None, tooltip=""):
        item = QTableWidgetItem(text)
        item.setForeground(_qcolor(color_hex))
        item.setBackground(_qcolor(bg_hex))
        item.setFont(font)
        item.setTextAlignment(align if align is not None else Qt.AlignmentFlag.AlignCenter)
        if tooltip:
            item.setToolTip(tooltip)
        table.setItem(row, col, item)

    def _on_summary_cell_double_clicked(self, row, _col):
        entry = getattr(self, "_summary_row_days", {}).get(row)
        if not entry:
            return
        region_name, day = entry
        if day:
            self._open_hourly_detail(region_name, day)

    def _on_summary_cell_clicked(self, row, col):
        if col != 0:
            return
        entry = getattr(self, "_summary_branch_rows", {}).get(row)
        if not entry:
            return
        branch_name, members = entry
        self._open_branch_range(branch_name, members)


def main():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    theme.init_app_theme()
    theme.load_bundled_fonts()
    app.setFont(theme.font(13, QFont.Weight.Normal))
    window = WeatherDutyApp()
    window.show()
    app.exec()
