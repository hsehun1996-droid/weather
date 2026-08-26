"""폭염/풍수해/제설 근무용 날씨 모니터 - PySide6 + PySide6-Fluent-Widgets(qfluentwidgets) GUI.

서버 없이 단일 실행 파일(개별 프로그램)로 동작하며, 기상청 API를 직접 호출한다.
디자인은 애플 시스템 설정의 "그래파이트"(무채색) 손잡이색을 참고해 파란색 대신
회색조 강조색을 쓰는 블랙 앤 화이트 톤으로 맞췄고, 위젯 자체는 PyQt-Fluent-Widgets
(https://github.com/zhiyiYo/PyQt-Fluent-Widgets)의 카드/세그먼트 컨트롤/토스트
알림 등을 그대로 가져다 쓴다.
"""
import re
import threading

from PySide6.QtCore import Qt, QObject, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QMainWindow, QFrame, QLabel, QVBoxLayout, QHBoxLayout,
    QDialog, QMessageBox, QInputDialog, QStackedWidget, QTableWidgetItem,
    QAbstractItemView, QAbstractScrollArea, QListWidgetItem,
)

from qfluentwidgets import (
    PushButton, PrimaryPushButton, TransparentPushButton, ToolButton,
    LineEdit, SearchLineEdit, ComboBox, CheckBox, TableWidget, ListWidget,
    ScrollArea, CardWidget, SegmentedWidget, InfoBar, InfoBarPosition,
    FluentIcon, SystemThemeListener,
)

from . import config, kma_client, regions, theme

_PCP_NUMBER_RE = re.compile(r"([\d.]+)")


def _pcp_numeric(pcp_str):
    """요약 화면에서 지사 내 최다 강수 지역을 고르기 위한 정렬용 숫자값."""
    if not pcp_str or pcp_str == "강수없음":
        return 0.0
    match = _PCP_NUMBER_RE.search(pcp_str)
    return float(match.group(1)) if match else 0.0


def _pcp_display_text(day):
    """강수량 칸에 보여줄 문구.
    - 단기예보(강수량 데이터 있음): "3mm" 같은 실제 값 또는 "강수없음"
    - 중기예보(원래 강수량 없이 확률만 제공): 값이 없는게 API 한계라는 걸 명시
    - 데이터 자체가 없음(조회 중/실패): "-" """
    if day is None:
        return "-"
    pcp = day.get("pcp")
    if pcp:
        return pcp
    if day.get("source") == "중기예보":
        return "중기예보(강수량 미제공)"
    return "강수없음" if day.get("pop") is not None else "-"


def _format_fcst_time(time_str):
    if time_str and len(time_str) >= 2:
        return f"{time_str[:2]}시"
    return time_str or "-"


def qss(color=None, bg=None, radius=None, pad=None, border=None, weight=None):
    decls = []
    if color:
        decls.append(f"color:{color}")
    if bg is not None:
        decls.append(f"background-color:{bg}")
    if radius is not None:
        decls.append(f"border-radius:{radius}px")
    if pad:
        decls.append(f"padding:{pad}")
    if border:
        decls.append(f"border:{border}")
    if weight:
        decls.append(f"font-weight:{weight}")
    return ";".join(decls) + ";"


def make_card(parent, c, radius=16):
    card = CardWidget(parent)
    card.setBorderRadius(radius)
    return card


def toast(parent, kind, title, content):
    """즉시 사라지는 토스트 알림(성공/오류 확인용). 저장/추가 같은 짧은 확인
    메시지에 쓰고, 사용자가 반드시 읽고 넘어가야 하는 입력 검증 오류는
    QMessageBox를 그대로 쓴다."""
    method = getattr(InfoBar, kind)
    method(
        title=title, content=content, orient=Qt.Orientation.Horizontal,
        isClosable=True, duration=2500, position=InfoBarPosition.TOP,
        parent=parent,
    )


class ClickableFrame(QFrame):
    doubleClicked = Signal()
    clicked = Signal()

    def mouseDoubleClickEvent(self, event):  # noqa: N802 - Qt override
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):  # noqa: N802 - Qt override
        self.clicked.emit()
        super().mousePressEvent(event)


def _bring_to_front(win):
    win.raise_()
    win.activateWindow()


def _clear_layout(layout):
    """레이아웃의 자식 위젯을 전부 제거한다. deleteLater()만 하면 실제 삭제가
    다음 이벤트 루프까지 미뤄져 새로 그린 위젯과 잠깐 겹쳐 보이므로, setParent(None)로
    화면에서 즉시 떼어낸 뒤 삭제를 예약한다."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()


# ---------------------------------------------------------------------------
# 다이얼로그
# ---------------------------------------------------------------------------


class _HorizontalWheelTable(TableWidget):
    """시간별 표는 세로줄이 몇 개 안 되고 가로(시각)로 길게 늘어서므로,
    마우스 휠(세로 스크롤 입력)을 가로 스크롤로 돌려준다."""

    def wheelEvent(self, event):  # noqa: N802 - Qt override
        delta = event.angleDelta().y() or event.angleDelta().x()
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - delta)
        event.accept()


class HourlyDetailDialog(QDialog):
    """일자별 예보 칸(지역별 상세/종합보기 어느 쪽이든)을 더블클릭하면 그 날의
    3시간 구간별 날씨/기온/체감온도/강수량/강수확률을 가로로 늘어놓은 표로 보여준다."""

    def __init__(self, parent, region_name, day):
        super().__init__(parent)
        c = theme.colors()
        pretty_date = day.get("date", "")
        if len(pretty_date) == 8:
            pretty_date = f"{pretty_date[:4]}-{pretty_date[4:6]}-{pretty_date[6:8]}"
        self.setWindowTitle(f"{region_name} {pretty_date} 시간별 예보")
        self.setStyleSheet(f"QDialog {{ background-color:{c['bg']}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        title = QLabel(f"{region_name}  ·  {pretty_date} 시간별 예보", self)
        title.setFont(parent.font_title)
        title.setStyleSheet(qss(color=c["text"]))
        layout.addWidget(title)

        hourly = day.get("hourly") or []
        summary_bits = [f"00~24시 누적 강수량: {_pcp_display_text(day)}"]
        if day.get("tmin") is not None or day.get("tmax") is not None:
            summary_bits.append(f"기온 {day.get('tmin', '-')}° / {day.get('tmax', '-')}°")
        if day.get("feels_like_min") is not None:
            summary_bits.append(f"체감 {day['feels_like_min']}° / {day['feels_like_max']}°")

        if not hourly:
            card = make_card(self, c)
            card_layout = QVBoxLayout(card)
            if day.get("source") == "중기예보":
                reason = "중기예보(4일 이후)는 기상청이 강수확률만 제공하고,\n3시간 단위 시간별 데이터는 제공하지 않습니다."
            elif day.get("source") == "실측":
                reason = "이 날짜의 시간별 실측 자료를 불러오지 못했습니다."
            else:
                reason = "시간별 데이터가 없습니다."
            reason_label = QLabel(reason, card)
            reason_label.setFont(parent.font_small)
            reason_label.setStyleSheet(qss(color=c["subtext"]))
            card_layout.addSpacing(24)
            card_layout.addWidget(reason_label)
            summary_label = QLabel("   |   ".join(summary_bits), card)
            summary_label.setFont(parent.font_body)
            summary_label.setStyleSheet(qss(color=c["text"]))
            card_layout.addWidget(summary_label)
            card_layout.addSpacing(24)
            layout.addWidget(card, 1)
            self.resize(400, 260)
        else:
            row_defs = [("날씨", "condition"), ("기온", "temp"), ("체감온도", "feels_like"), ("강수량", "pcp"), ("강수확률", "pop")]
            label_col_w, hour_col_w = 112, 92
            table = _HorizontalWheelTable(self)
            table.setRowCount(len(row_defs) + 1)
            table.setColumnCount(len(hourly) + 1)
            table.horizontalHeader().hide()
            table.verticalHeader().hide()
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            table.setBorderRadius(12)
            table.setColumnWidth(0, label_col_w)
            for row_idx, (label, _key) in enumerate([("시각", None)] + row_defs):
                item = QTableWidgetItem(label)
                item.setForeground(_qcolor(c["subtext"]))
                item.setFont(parent.font_body)
                table.setItem(row_idx, 0, item)

            for offset, hour in enumerate(hourly):
                col = offset + 1
                table.setColumnWidth(col, hour_col_w)
                _set_cell(table, 0, col, _format_fcst_time(hour.get("time")), c["text"], parent.font_body)
                _set_cell(table, 1, col, hour.get("condition") or "-", c["subtext"], parent.font_small)
                temp = hour.get("temp")
                _set_cell(table, 2, col, (f"{temp}°" if temp is not None else "-"), c["text"], parent.font_body)
                feels_like = hour.get("feels_like")
                _set_cell(
                    table, 3, col, (f"{feels_like:.1f}°" if feels_like is not None else "-"),
                    c["text"], parent.font_body,
                )
                _set_cell(table, 4, col, hour.get("pcp") or "-", c["subtext"], parent.font_small)
                pop_val = hour.get("pop")
                _set_cell(
                    table, 5, col, (f"{pop_val}%" if pop_val is not None else "-"),
                    theme.pop_color(pop_val, c), parent.font_small,
                )

            layout.addWidget(table, 1)

            summary_card = make_card(self, c, radius=10)
            summary_layout = QVBoxLayout(summary_card)
            summary_label = QLabel("   |   ".join(summary_bits), summary_card)
            summary_label.setFont(parent.font_body)
            summary_label.setStyleSheet(qss(color=c["text"]))
            summary_layout.addWidget(summary_label)
            layout.addWidget(summary_card)

            self.resize(820, 440)

        close_btn = PushButton("닫기", self)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        _bring_to_front(self)


def _qcolor(hex_str):
    from PySide6.QtGui import QColor
    return QColor(hex_str)


def _set_cell(table, row, col, text, color_hex, font):
    item = QTableWidgetItem(text)
    item.setForeground(_qcolor(color_hex))
    item.setFont(font)
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    table.setItem(row, col, item)


class RegionManagerDialog(QDialog):
    def __init__(self, parent, on_change):
        super().__init__(parent)
        c = theme.colors()
        self.setWindowTitle("즐겨찾기 편집")
        self.resize(480, 560)
        self.on_change = on_change
        self.favorites = set(config.get_favorites())
        self.font_body = parent.font_body
        self.font_small = parent.font_small
        self.setStyleSheet(f"QDialog {{ background-color:{c['bg']}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        hint = QLabel("지역을 검색해 즐겨찾기에 추가/삭제하세요.", self)
        hint.setFont(self.font_body)
        hint.setStyleSheet(qss(color=c["text"]))
        layout.addWidget(hint)

        self.search_edit = SearchLineEdit(self)
        self.search_edit.setPlaceholderText("예: 수원, 강남구, 안동시")
        self.search_edit.textChanged.connect(self._render_results)
        layout.addWidget(self.search_edit)

        self.scroll = ScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.results_frame = QWidget()
        self.results_frame.setStyleSheet("background: transparent;")
        self.results_layout = QVBoxLayout(self.results_frame)
        self.results_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.results_frame)
        layout.addWidget(self.scroll, 1)

        btn_row = QHBoxLayout()
        add_btn = PushButton("위도/경도로 직접 추가", self, FluentIcon.ADD)
        add_btn.clicked.connect(self._open_custom_region_form)
        btn_row.addWidget(add_btn)
        btn_row.addStretch(1)
        close_btn = PushButton("닫기", self)
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

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

    def _render_results(self, *_args):
        _clear_layout(self.results_layout)

        query = self.search_edit.text().strip()
        names = self._current_matches()
        c = theme.colors()
        if not query and not names:
            label = QLabel("아직 즐겨찾기가 없습니다. 위 검색창에 지역명을 입력하세요.", self.results_frame)
            label.setFont(self.font_small)
            label.setStyleSheet(qss(color=c["subtext"]))
            self.results_layout.addWidget(label)
            return
        if query and not names:
            label = QLabel("검색 결과가 없습니다.", self.results_frame)
            label.setFont(self.font_small)
            label.setStyleSheet(qss(color=c["subtext"]))
            self.results_layout.addWidget(label)
            return

        custom_names = set(regions.load_custom_regions().keys())
        for name in names:
            label = name + ("  [직접 추가]" if name in custom_names else "")
            checkbox = CheckBox(label, self.results_frame)
            checkbox.setFont(self.font_body)
            checkbox.setChecked(name in self.favorites)
            checkbox.stateChanged.connect(lambda _state, n=name, cb=checkbox: self._toggle(n, cb))
            self.results_layout.addWidget(checkbox)

    def _toggle(self, name, checkbox):
        if checkbox.isChecked():
            self.favorites.add(name)
            config.set_favorites(sorted(self.favorites))
            self.on_change(added=name)
        else:
            self.favorites.discard(name)
            config.set_favorites(sorted(self.favorites))
            self.on_change(removed=name)

    def _open_custom_region_form(self):
        CustomRegionForm(self, self._render_results)


class CustomRegionForm(QDialog):
    def __init__(self, parent, on_saved):
        super().__init__(parent)
        c = theme.colors()
        self.setWindowTitle("지역 직접 추가")
        self.resize(380, 420)
        self.on_saved = on_saved
        self.setStyleSheet(f"QDialog {{ background-color:{c['bg']}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        fields = [
            ("name", "지역 이름 (예: 우리동네)"),
            ("lat", "위도 (예: 37.5665)"),
            ("lon", "경도 (예: 126.9780)"),
        ]
        self.edits = {}
        for key, placeholder in fields:
            label = QLabel(placeholder, self)
            label.setStyleSheet(qss(color=c["text"]))
            layout.addWidget(label)
            edit = LineEdit(self)
            layout.addWidget(edit)
            self.edits[key] = edit

        sido_label = QLabel("시도 (중기예보 권역 판별용)", self)
        sido_label.setStyleSheet(qss(color=c["text"]))
        layout.addWidget(sido_label)
        self.sido_combo = ComboBox(self)
        self.sido_combo.addItems(regions.SIDO_NAMES)
        layout.addWidget(self.sido_combo)

        note = QLabel(
            "위도/경도는 구글맵 등 지도에서 원하는 위치를 우클릭하면 확인할 수 있습니다.",
            self,
        )
        note.setWordWrap(True)
        note.setStyleSheet(qss(color=c["subtext"]))
        layout.addWidget(note)
        layout.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = PushButton("취소", self)
        cancel_btn.clicked.connect(self.close)
        btn_row.addWidget(cancel_btn)
        save_btn = PrimaryPushButton("추가", self)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        _bring_to_front(self)

    def _save(self):
        name = self.edits["name"].text().strip()
        try:
            lat = float(self.edits["lat"].text().strip())
            lon = float(self.edits["lon"].text().strip())
        except ValueError:
            QMessageBox.warning(self, "입력 오류", "위도/경도는 숫자로 입력하세요.")
            return
        if not name:
            QMessageBox.warning(self, "입력 필요", "지역 이름을 입력하세요.")
            return
        regions.add_custom_region(name, lat, lon, self.sido_combo.currentText())
        config.add_favorite(name)
        self.parent().favorites.add(name)
        self.on_saved()
        self.parent().on_change(added=name)
        toast(self.parent(), "success", "추가됨", f"'{name}'을(를) 즐겨찾기에 추가했습니다.")
        self.close()


class BranchRangeDialog(QDialog):
    """지사 이름을 클릭하면 뜨는 창: 날짜와 시간대(시작~종료)를 골라 그 구간의
    누적강수량을 지사 관할 지역별로 비교하고, 가장 많은 지역을 하이라이트한다.
    지난 실측 2일 + 단기예보 날짜를 고를 수 있다. 중기예보(4일 이후)는 3시간 단위
    시간별 데이터를 제공하지 않아 날짜 선택 대상에서 제외한다."""

    def __init__(self, parent, branch_name, members, reports):
        super().__init__(parent)
        c = theme.colors()
        self.branch_name = branch_name
        self.members = members
        self.reports = reports
        self.font_title = parent.font_title
        self.font_body = parent.font_body
        self.font_small = parent.font_small
        self.setWindowTitle(f"{branch_name} - 시간대별 누적강수량")
        self.resize(460, 580)
        self.setStyleSheet(f"QDialog {{ background-color:{c['bg']}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel(f"{branch_name} 관할 지역 시간대별 누적강수량", self)
        title.setFont(self.font_title)
        title.setStyleSheet(qss(color=c["text"]))
        layout.addWidget(title)

        note = QLabel(
            "중기예보(4일 이후)는 시간별 데이터가 없어 선택할 수 없습니다.\n(지난 실측 2일은 선택 가능)",
            self,
        )
        note.setFont(self.font_small)
        note.setStyleSheet(qss(color=c["subtext"]))
        layout.addWidget(note)

        self.dates = self._short_term_dates()

        if not self.dates:
            empty = QLabel(
                "선택 가능한 날짜가 없습니다.\n(즐겨찾기 조회가 끝난 뒤 다시 시도하세요)", self
            )
            empty.setFont(self.font_small)
            empty.setStyleSheet(qss(color=c["subtext"]))
            layout.addWidget(empty)
            layout.addStretch(1)
            close_btn = PushButton("닫기", self)
            close_btn.clicked.connect(self.close)
            layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignHCenter)
            _bring_to_front(self)
            return

        picker_row = QHBoxLayout()
        date_label_hdr = QLabel("날짜", self)
        date_label_hdr.setFont(self.font_body)
        date_label_hdr.setStyleSheet(qss(color=c["subtext"]))
        picker_row.addWidget(date_label_hdr)

        self.date_seg = SegmentedWidget(self)
        for d in self.dates:
            self.date_seg.addItem(d, f"{d[4:6]}/{d[6:8]}", onClick=lambda _c=False, dd=d: self._on_date_changed(dd))
        picker_row.addWidget(self.date_seg, 1)
        layout.addLayout(picker_row)

        time_row = QHBoxLayout()
        start_hdr = QLabel("시작", self)
        start_hdr.setFont(self.font_body)
        start_hdr.setStyleSheet(qss(color=c["subtext"]))
        time_row.addWidget(start_hdr)
        self.start_combo = ComboBox(self)
        self.start_combo.currentTextChanged.connect(lambda _v: self._render())
        time_row.addWidget(self.start_combo)
        end_hdr = QLabel("종료", self)
        end_hdr.setFont(self.font_body)
        end_hdr.setStyleSheet(qss(color=c["subtext"]))
        time_row.addWidget(end_hdr)
        self.end_combo = ComboBox(self)
        self.end_combo.currentTextChanged.connect(lambda _v: self._render())
        time_row.addWidget(self.end_combo)
        time_row.addStretch(1)
        layout.addLayout(time_row)

        self.result_scroll = ScrollArea(self)
        self.result_scroll.setWidgetResizable(True)
        result_card = make_card(self, c, radius=12)
        self.result_layout = QVBoxLayout(result_card)
        self.result_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.result_scroll.setWidget(result_card)
        self.result_scroll.setStyleSheet("QScrollArea { border: none; }")
        layout.addWidget(self.result_scroll, 1)

        close_btn = PushButton("닫기", self)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignHCenter)

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

    def _render(self):
        _clear_layout(self.result_layout)

        c = theme.colors()
        date_str = getattr(self, "_current_date", None)
        start_hour = self._selected_hour(self.start_combo.currentText())
        end_hour = self._selected_hour(self.end_combo.currentText())
        if date_str is None or start_hour is None or end_hour is None:
            return
        if start_hour >= end_hour:
            warn = QLabel("시작 시각은 종료 시각보다 앞서야 합니다.", self)
            warn.setFont(self.font_small)
            warn.setStyleSheet(qss(color=c["warn_text"]))
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
        header.setFont(self.font_body)
        header.setStyleSheet(qss(color=c["text"]))
        self.result_layout.addWidget(header)

        for name, pcp_text, amount in rows:
            is_best = name == best_name and best_amount > 0
            row = QFrame(self)
            row.setStyleSheet(qss(bg=(c["warn_bg"] if is_best else "transparent"), radius=8))
            row_layout = QHBoxLayout(row)
            name_label = QLabel(name, row)
            name_label.setFont(self.font_body)
            name_label.setStyleSheet(qss(color=(c["warn_text"] if is_best else c["text"])))
            row_layout.addWidget(name_label, 1)
            value_label = QLabel(("★ " if is_best else "") + pcp_text, row)
            value_font = QFont(self.font_body)
            value_font.setBold(is_best)
            value_label.setFont(value_font)
            value_label.setStyleSheet(qss(color=(c["warn_text"] if is_best else c["text"])))
            row_layout.addWidget(value_label)
            self.result_layout.addWidget(row)


class BranchManagerDialog(QDialog):
    """지사(관할 구역) 관리: 지사별로 어떤 즐겨찾기 지역이 속하는지 편집.
    '즐겨찾기 종합 보기'에서 지사 단위로 묶어서 보여주는 데 쓰인다."""

    def __init__(self, parent, on_change):
        super().__init__(parent)
        c = theme.colors()
        self.setWindowTitle("지사 관리")
        self.resize(460, 600)
        self.on_change = on_change
        self.font_body = parent.font_body
        self.font_small = parent.font_small
        self.setStyleSheet(f"QDialog {{ background-color:{c['bg']}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        note = QLabel(
            "지사별로 즐겨찾기 지역을 묶어서 관리합니다. 지역 하나가 여러 지사에\n동시에 속할 수도 있습니다.",
            self,
        )
        note.setFont(self.font_small)
        note.setStyleSheet(qss(color=c["subtext"]))
        layout.addWidget(note)

        self.scroll = ScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.list_frame = QWidget()
        self.list_frame.setStyleSheet("background: transparent;")
        self.list_layout = QVBoxLayout(self.list_frame)
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.list_frame)
        layout.addWidget(self.scroll, 1)

        btn_row = QHBoxLayout()
        add_btn = PushButton("새 지사 추가", self, FluentIcon.ADD)
        add_btn.clicked.connect(self._add_branch)
        btn_row.addWidget(add_btn)
        btn_row.addStretch(1)
        close_btn = PushButton("닫기", self)
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._render()
        _bring_to_front(self)

    def _render(self):
        _clear_layout(self.list_layout)

        c = theme.colors()
        branches = config.get_branches()
        if not branches:
            empty = QLabel("아직 지사가 없습니다. '새 지사 추가'로 만드세요.", self.list_frame)
            empty.setFont(self.font_small)
            empty.setStyleSheet(qss(color=c["subtext"]))
            self.list_layout.addWidget(empty)
            return

        for branch_name in sorted(branches):
            section = make_card(self.list_frame, c, radius=12)
            section_layout = QVBoxLayout(section)

            header = QHBoxLayout()
            name_label = QLabel(branch_name, section)
            name_label.setFont(self.font_body)
            name_label.setStyleSheet(qss(color=c["text"]))
            header.addWidget(name_label, 1)
            del_btn = TransparentPushButton("지사 삭제", section, FluentIcon.DELETE)
            del_btn.clicked.connect(lambda _c=False, b=branch_name: self._remove_branch(b))
            header.addWidget(del_btn)
            section_layout.addLayout(header)

            for region_name in branches[branch_name]:
                row = QHBoxLayout()
                region_label = QLabel(region_name, section)
                region_label.setFont(self.font_small)
                region_label.setStyleSheet(qss(color=c["subtext"]))
                row.addWidget(region_label, 1)
                remove_btn = TransparentPushButton("제거", section)
                remove_btn.clicked.connect(
                    lambda _c=False, b=branch_name, r=region_name: self._remove_region(b, r)
                )
                row.addWidget(remove_btn)
                section_layout.addLayout(row)

            add_row = QHBoxLayout()
            search_edit = LineEdit(section)
            search_edit.setPlaceholderText("즐겨찾기 지역 검색해서 추가")
            add_row.addWidget(search_edit, 1)
            add_btn = PushButton("추가", section)
            add_btn.clicked.connect(
                lambda _c=False, b=branch_name, e=search_edit: self._add_region_from_search(b, e)
            )
            add_row.addWidget(add_btn)
            section_layout.addLayout(add_row)

            self.list_layout.addWidget(section)

    def _add_region_from_search(self, branch_name, search_edit):
        query = search_edit.text().strip()
        if not query:
            return
        favorites = config.get_favorites()
        matches = [n for n in favorites if query in n]
        if not matches:
            QMessageBox.information(
                self, "검색 결과 없음", "일치하는 즐겨찾기 지역이 없습니다. 먼저 즐겨찾기에 추가하세요."
            )
            return
        if len(matches) > 1:
            QMessageBox.information(
                self, "여러 개 일치",
                "검색어와 일치하는 지역이 여러 개입니다:\n" + "\n".join(matches[:10]) + "\n더 구체적으로 입력하세요.",
            )
            return
        config.add_region_to_branch(branch_name, matches[0])
        self._render()
        self.on_change()

    def _remove_region(self, branch_name, region_name):
        config.remove_region_from_branch(branch_name, region_name)
        self._render()
        self.on_change()

    def _remove_branch(self, branch_name):
        config.remove_branch(branch_name)
        self._render()
        self.on_change()

    def _add_branch(self):
        name, ok = QInputDialog.getText(self, "새 지사 추가", "지사 이름:")
        if not ok or not name.strip():
            return
        config.add_branch(name.strip())
        self._render()
        self.on_change()
        toast(self.parent(), "success", "지사 추가됨", f"'{name.strip()}' 지사를 추가했습니다.")


class SettingsDialog(QDialog):
    def __init__(self, parent, on_change):
        super().__init__(parent)
        c = theme.colors()
        self.setWindowTitle("설정 - 기상청 서비스키")
        self.resize(520, 200)
        self.on_change = on_change
        self.setStyleSheet(f"QDialog {{ background-color:{c['bg']}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        note = QLabel("공공데이터포털(data.go.kr)에서 발급받은 서비스키(디코딩 키)를 입력하세요.", self)
        note.setWordWrap(True)
        note.setStyleSheet(qss(color=c["text"]))
        layout.addWidget(note)

        self.key_edit = LineEdit(self)
        self.key_edit.setText(config.get_service_key())
        self.key_edit.setEchoMode(LineEdit.EchoMode.Password)
        layout.addWidget(self.key_edit)

        self.show_checkbox = CheckBox("키 표시", self)
        self.show_checkbox.stateChanged.connect(self._toggle_show)
        layout.addWidget(self.show_checkbox)
        layout.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = PushButton("취소", self)
        cancel_btn.clicked.connect(self.close)
        btn_row.addWidget(cancel_btn)
        save_btn = PrimaryPushButton("저장", self)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        _bring_to_front(self)

    def _toggle_show(self):
        self.key_edit.setEchoMode(
            LineEdit.EchoMode.Normal if self.show_checkbox.isChecked() else LineEdit.EchoMode.Password
        )

    def _save(self):
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
        self.resize(1180, 700)
        self.setMinimumSize(960, 600)

        self.font_display = theme.font(46, QFont.Weight.Bold)
        self.font_title = theme.font(19, QFont.Weight.Bold)
        self.font_subtitle = theme.font(14, QFont.Weight.Medium)
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
        self.root_layout.setContentsMargins(16, 14, 16, 16)
        self.root_layout.setSpacing(6)

        self._build_toolbar()
        self._build_layout()
        self._apply_window_style()

        QTimer.singleShot(200, self.refresh_all)

    def closeEvent(self, event):  # noqa: N802 - Qt override
        self._theme_listener.terminate()
        self._theme_listener.wait()
        super().closeEvent(event)

    # ---------- style ----------
    def _apply_window_style(self):
        self.centralWidget().setStyleSheet(f"background-color:{theme.colors()['bg']};")

    def _on_theme_changed(self):
        self._apply_window_style()
        self._rebuild_ui()

    def _rebuild_ui(self):
        # 팔레트가 바뀌면 위젯을 통째로 다시 만든다 (매번 렌더링 함수가 위젯을
        # 새로 그리는 이 앱의 구조를 그대로 활용한다).
        old_central = self.centralWidget()
        central = QWidget(self)
        self.setCentralWidget(central)
        self.root_layout = QVBoxLayout(central)
        self.root_layout.setContentsMargins(16, 14, 16, 16)
        self.root_layout.setSpacing(6)
        self._build_toolbar()
        self._build_layout()
        self._apply_window_style()
        old_central.setParent(None)
        old_central.deleteLater()
        self._sync_view_mode_widgets()
        self._refresh_current_view()

    # ---------- layout ----------
    def _build_toolbar(self):
        c = theme.colors()
        toolbar = QWidget(self)
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("폭염·풍수해·제설 근무 날씨 모니터", toolbar)
        title.setFont(self.font_title)
        title.setStyleSheet(qss(color=c["text"]))
        toolbar_layout.addWidget(title)
        toolbar_layout.addStretch(1)

        self.status_label = QLabel("", toolbar)
        self.status_label.setFont(self.font_small)
        self.status_label.setStyleSheet(qss(color=c["subtext"]))
        toolbar_layout.addWidget(self.status_label)

        refresh_btn = PushButton("새로고침", toolbar, FluentIcon.SYNC)
        refresh_btn.clicked.connect(self.refresh_all)
        toolbar_layout.addWidget(refresh_btn)

        self.view_seg = SegmentedWidget(toolbar)
        self.view_seg.addItem("detail", "지역별 상세", onClick=lambda: self._set_view_mode("detail"))
        self.view_seg.addItem("summary", "즐겨찾기 종합", onClick=lambda: self._set_view_mode("summary"))
        self.view_seg.setCurrentItem(self.view_mode)
        toolbar_layout.addWidget(self.view_seg)

        region_btn = PushButton("즐겨찾기 편집", toolbar, FluentIcon.EDIT)
        region_btn.clicked.connect(self._open_region_manager)
        toolbar_layout.addWidget(region_btn)

        branch_btn = PushButton("지사 관리", toolbar, FluentIcon.PEOPLE)
        branch_btn.clicked.connect(self._open_branch_manager)
        toolbar_layout.addWidget(branch_btn)

        settings_btn = ToolButton(FluentIcon.SETTING, toolbar)
        settings_btn.clicked.connect(self._open_settings)
        toolbar_layout.addWidget(settings_btn)

        self.root_layout.addWidget(toolbar)

    def _build_layout(self):
        c = theme.colors()
        body = QWidget(self)
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(16)
        self.root_layout.addWidget(body, 1)

        sidebar = make_card(body, c, radius=16)
        sidebar.setFixedWidth(250)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 16, 8, 8)
        body_layout.addWidget(sidebar)

        sidebar_hdr = QLabel("즐겨찾기 지역", sidebar)
        sidebar_hdr.setFont(self.font_body)
        sidebar_hdr.setStyleSheet(qss(color=c["subtext"]))
        sidebar_layout.addWidget(sidebar_hdr)

        self.favorites_list = ListWidget(sidebar)
        self.favorites_list.setStyleSheet("QListWidget { background: transparent; border: none; }")
        self.favorites_list.itemClicked.connect(self._on_favorite_item_clicked)
        sidebar_layout.addWidget(self.favorites_list, 1)

        self.stack = QStackedWidget(body)
        body_layout.addWidget(self.stack, 1)

        self.detail_page = QWidget(self.stack)
        self._build_detail_widgets(self.detail_page)
        self.stack.addWidget(self.detail_page)

        self.summary_page = QWidget(self.stack)
        self._build_summary_widgets(self.summary_page)
        self.stack.addWidget(self.summary_page)

        self.stack.setCurrentWidget(self.detail_page)

    def _build_detail_widgets(self, parent):
        c = theme.colors()
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header = make_card(parent, c, radius=16)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 18, 20, 18)
        layout.addWidget(header)

        top_row = QHBoxLayout()
        self.region_name_label = QLabel("즐겨찾기 지역을 선택하세요", header)
        self.region_name_label.setFont(self.font_title)
        self.region_name_label.setStyleSheet(qss(color=c["text"]))
        top_row.addWidget(self.region_name_label)
        top_row.addStretch(1)
        self.obs_time_label = QLabel("", header)
        self.obs_time_label.setFont(self.font_small)
        self.obs_time_label.setStyleSheet(qss(color=c["subtext"]))
        top_row.addWidget(self.obs_time_label)
        header_layout.addLayout(top_row)

        current_row = QHBoxLayout()
        self.temp_label = QLabel("-℃", header)
        self.temp_label.setFont(self.font_display)
        self.temp_label.setStyleSheet(qss(color=c["text"]))
        current_row.addWidget(self.temp_label)

        detail_col = QVBoxLayout()
        self.rain_label = QLabel("1시간 강수량 -mm", header)
        self.rain_label.setFont(self.font_body)
        self.rain_label.setStyleSheet(qss(color=c["subtext"]))
        detail_col.addWidget(self.rain_label)
        self.error_label = QLabel("", header)
        self.error_label.setFont(self.font_small)
        self.error_label.setStyleSheet(qss(color=c["warn_text"]))
        self.error_label.setWordWrap(True)
        detail_col.addWidget(self.error_label)
        current_row.addLayout(detail_col)
        current_row.addStretch(1)
        header_layout.addLayout(current_row)

        self.warning_banner = QLabel("현재 발효 중인 특보 없음", header)
        self.warning_banner.setFont(self.font_body)
        self.warning_banner.setWordWrap(True)
        self.warning_banner.setStyleSheet(qss(color=c["ok_text"], bg=c["ok_bg"], radius=10, pad="10px"))
        header_layout.addWidget(self.warning_banner)

        sub_hdr = QLabel("지난 실측 2일 + 향후 예보 (가져올 수 있는 최대 기간)", parent)
        sub_hdr.setFont(self.font_body)
        sub_hdr.setStyleSheet(qss(color=c["subtext"]))
        layout.addWidget(sub_hdr)

        self.forecast_scroll = ScrollArea(parent)
        self.forecast_scroll.setWidgetResizable(True)
        forecast_card = make_card(parent, c, radius=16)
        self.forecast_layout = QVBoxLayout(forecast_card)
        self.forecast_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.forecast_scroll.setWidget(forecast_card)
        self.forecast_scroll.setStyleSheet("QScrollArea { border: none; }")
        layout.addWidget(self.forecast_scroll, 1)

    def _build_summary_widgets(self, parent):
        c = theme.colors()
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        date_bar = make_card(parent, c, radius=16)
        date_bar_layout = QHBoxLayout(date_bar)
        date_bar_layout.setContentsMargins(16, 12, 16, 12)
        date_hdr = QLabel("날짜 선택", date_bar)
        date_hdr.setFont(self.font_body)
        date_hdr.setStyleSheet(qss(color=c["subtext"]))
        date_bar_layout.addWidget(date_hdr)
        self.summary_date_selector = SegmentedWidget(date_bar)
        date_bar_layout.addWidget(self.summary_date_selector, 1)
        layout.addWidget(date_bar)

        self.summary_hint = QLabel(
            "※ 지사명을 클릭하면 원하는 날짜·시간대의 누적강수량을 관할 지역별로 비교할 수 있습니다.",
            parent,
        )
        self.summary_hint.setFont(self.font_small)
        self.summary_hint.setStyleSheet(qss(color=c["subtext"]))
        layout.addWidget(self.summary_hint)

        self.summary_table = TableWidget(parent)
        self.summary_table.setColumnCount(7)
        self.summary_table.setHorizontalHeaderLabels(
            ["지사", "지역", "최저/최고", "체감 최저/최고", "강수확률", "강수량(00~24시 누적)", "특보"]
        )
        self.summary_table.verticalHeader().hide()
        self.summary_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.summary_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.summary_table.setBorderRadius(16)
        self.summary_table.horizontalHeader().setStretchLastSection(False)
        self.summary_table.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self.summary_table.cellDoubleClicked.connect(self._on_summary_cell_double_clicked)
        self.summary_table.cellClicked.connect(self._on_summary_cell_clicked)
        layout.addWidget(self.summary_table, 1)

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
            self.status_label.setText("서비스키 미설정 - '설정'에서 입력하세요")
            self.reports = {}
            self._refresh_current_view()
            return

        favorites = config.get_favorites()
        self.status_label.setText("조회 중...")
        self._fetch_seq += 1
        seq = self._fetch_seq
        for name in favorites:
            self.reports.pop(name, None)
        self._refresh_current_view()

        threading.Thread(target=self._fetch_all, args=(service_key, favorites, seq), daemon=True).start()

    def _fetch_all(self, service_key, favorites, seq):
        all_regions = regions.all_regions()
        try:
            warnings = kma_client.get_active_warnings(service_key)
            warnings_error = None
        except Exception as exc:  # noqa: BLE001
            warnings = []
            warnings_error = str(exc)

        reports = {}
        for name in favorites:
            info = all_regions.get(name)
            if not info:
                continue
            report = kma_client.build_region_report(service_key, name, info, warnings)
            if warnings_error:
                report["errors"].append(f"특보 조회 실패: {warnings_error}")
            reports[name] = report

        self._bridge.all_done.emit(seq, reports, favorites)

    def _apply_fetch_result(self, seq, reports, favorites):
        if seq != self._fetch_seq:
            return  # 새 새로고침이 이미 시작돼 이 결과는 낡은 것 -> 버린다
        self.status_label.setText("갱신 완료")
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
            warnings = kma_client.get_active_warnings(service_key)
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
            item = QListWidgetItem("즐겨찾기가 비어 있습니다.\n'즐겨찾기 편집'에서 추가하세요.")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable & ~Qt.ItemFlag.ItemIsEnabled)
            item.setForeground(_qcolor(c["subtext"]))
            self.favorites_list.addItem(item)
            return

        for name in favorites:
            is_loading = name not in self.reports
            item = QListWidgetItem(("조회 중…  " + name) if is_loading else name)
            item.setFont(self.font_body)
            item.setData(Qt.ItemDataRole.UserRole, name)
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
        c = theme.colors()
        report = self.reports.get(name)
        if not report:
            self.region_name_label.setText(name)
            self.temp_label.setText("조회 중…")
            return

        current = report.get("current") or {}
        temp = current.get("temp")
        rain = current.get("rain_1h")
        obs_time = current.get("obs_time", "-")

        self.region_name_label.setText(name)
        self.temp_label.setText(f"{temp}℃" if temp is not None else "-℃")
        self.rain_label.setText(f"1시간 강수량 {rain if rain is not None else '-'}mm")
        self.obs_time_label.setText(f"관측시각 {obs_time}")

        errors = report.get("errors") or []
        self.error_label.setText("\n".join(errors))

        warnings = report.get("warnings") or []
        if warnings:
            self.warning_banner.setText("⚠ 특보 발효 중: " + " | ".join(warnings))
            self.warning_banner.setStyleSheet(
                qss(color=c["warn_text"], bg=c["warn_bg"], radius=10, pad="10px")
            )
        else:
            self.warning_banner.setText("현재 발효 중인 특보 없음  (당일 기준, 향후 예정일은 표시되지 않음)")
            self.warning_banner.setStyleSheet(
                qss(color=c["ok_text"], bg=c["ok_bg"], radius=10, pad="10px")
            )

        self._render_forecast(name, report.get("forecast", []))

    def _render_forecast(self, region_name, days):
        c = theme.colors()
        _clear_layout(self.forecast_layout)

        if not days:
            label = QLabel("예보 데이터가 없습니다.", self.forecast_scroll.widget())
            label.setFont(self.font_body)
            label.setStyleSheet(qss(color=c["subtext"]))
            self.forecast_layout.addWidget(label)
            return

        parent_widget = self.forecast_scroll.widget()
        for day in days:
            row = ClickableFrame(parent_widget)
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.setStyleSheet("QFrame { background: transparent; }")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(4, 6, 4, 6)

            date_str = day.get("date") or ""
            pretty_date = f"{date_str[4:6]}/{date_str[6:8]}" if len(date_str) == 8 else date_str

            date_label = QLabel(pretty_date, row)
            date_label.setFont(self.font_body)
            date_label.setStyleSheet(qss(color=c["text"]))
            date_label.setMinimumWidth(60)
            row_layout.addWidget(date_label)

            condition_label = QLabel(day.get("condition") or "-", row)
            condition_label.setFont(self.font_body)
            condition_label.setStyleSheet(qss(color=c["subtext"]))
            condition_label.setMinimumWidth(130)
            row_layout.addWidget(condition_label)

            pop = day.get("pop")
            pop_text = f"강수확률 {pop}%" if pop is not None else "강수확률 -"
            pop_label = QLabel(pop_text, row)
            pop_label.setFont(self.font_small)
            pop_label.setStyleSheet(qss(color=theme.pop_color(pop, c)))
            pop_label.setMinimumWidth(90)
            row_layout.addWidget(pop_label)

            pcp_label = QLabel(f"강수량 {_pcp_display_text(day)}", row)
            pcp_label.setFont(self.font_small)
            pcp_label.setStyleSheet(qss(color=c["subtext"]))
            pcp_label.setMinimumWidth(190)
            row_layout.addWidget(pcp_label)

            fl_min, fl_max = day.get("feels_like_min"), day.get("feels_like_max")
            if fl_min is not None:
                feels_label = QLabel(f"체감 {fl_min}° / {fl_max}°", row)
                feels_label.setFont(self.font_small)
                feels_label.setStyleSheet(qss(color=c["text"]))
                row_layout.addWidget(feels_label)

            row_layout.addStretch(1)

            source_label = QLabel(day.get("source") or "", row)
            source_label.setFont(self.font_small)
            source_label.setStyleSheet(qss(color=c["subtext"]))
            source_label.setMinimumWidth(70)
            source_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row_layout.addWidget(source_label)

            tmin, tmax = day.get("tmin"), day.get("tmax")
            temp_text = f"{tmin}° / {tmax}°" if (tmin or tmax) else "-"
            temp_label = QLabel(temp_text, row)
            temp_label.setFont(self.font_body)
            temp_label.setStyleSheet(qss(color=c["text"]))
            temp_label.setMinimumWidth(110)
            temp_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row_layout.addWidget(temp_label)

            row.doubleClicked.connect(lambda n=region_name, d=day: self._open_hourly_detail(n, d))
            self.forecast_layout.addWidget(row)

            separator = QFrame(parent_widget)
            separator.setFixedHeight(1)
            separator.setStyleSheet(f"background-color:{c['border']};")
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
        import datetime

        self.summary_date_selector.clear()
        if not all_dates:
            return

        for date_str in all_dates:
            pretty = f"{date_str[4:6]}/{date_str[6:8]}" if len(date_str) == 8 else date_str
            self.summary_date_selector.addItem(
                date_str, pretty, onClick=lambda _c=False, d=date_str: self._on_summary_date_selected(d)
            )

        if self.selected_summary_date not in all_dates:
            # 지난 실측 날짜가 목록 맨 앞에 추가되므로, 처음 열 때는 과거 날짜가 아니라
            # 오늘(또는 오늘이 없으면 가장 빠른 미래 날짜)을 기본으로 보여준다.
            today_str = datetime.datetime.now().strftime("%Y%m%d")
            self.selected_summary_date = next((d for d in all_dates if d >= today_str), all_dates[0])
        self.summary_date_selector.setCurrentItem(self.selected_summary_date)

    def _render_summary(self, favorites):
        c = theme.colors()
        table = self.summary_table
        table.setRowCount(0)
        self._summary_row_days = {}
        self._summary_branch_rows = {}

        if not favorites:
            table.setRowCount(1)
            item = QTableWidgetItem("즐겨찾기가 비어 있습니다.")
            item.setForeground(_qcolor(c["subtext"]))
            table.setItem(0, 1, item)
            return

        all_dates = self._all_summary_dates(favorites)
        self._update_summary_date_selector(all_dates)

        if not all_dates:
            table.setRowCount(1)
            item = QTableWidgetItem("예보 데이터를 불러오는 중입니다…")
            item.setForeground(_qcolor(c["subtext"]))
            table.setItem(0, 1, item)
            return

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
                is_best = region_name == best_name and best_amount > 0
                row_bg = c["warn_bg"] if is_best else c["card"]
                emph_color = c["warn_text"] if is_best else c["text"]

                self._summary_row_days[row_idx] = (region_name, day)

                name_text = ("조회 중… " + region_name) if is_loading else region_name
                self._set_summary_item(table, row_idx, 1, name_text, emph_color, row_bg, self.font_body)

                tmin, tmax = (day.get("tmin"), day.get("tmax")) if day else (None, None)
                temp_text = f"{tmin}°/{tmax}°" if (tmin is not None or tmax is not None) else "-"
                self._set_summary_item(table, row_idx, 2, temp_text, c["text"], row_bg, self.font_small)

                fl_min, fl_max = (day.get("feels_like_min"), day.get("feels_like_max")) if day else (None, None)
                if fl_min is not None:
                    feels_text = f"{fl_min}°/{fl_max}°"
                elif day and day.get("source") == "중기예보":
                    feels_text = "중기예보만"
                else:
                    feels_text = "-"
                self._set_summary_item(table, row_idx, 3, feels_text, c["text"], row_bg, self.font_small)

                pop = day.get("pop") if day else None
                pop_text = f"{pop}%" if pop is not None else "-"
                self._set_summary_item(
                    table, row_idx, 4, pop_text, theme.pop_color(pop, c), row_bg, self.font_small
                )

                if day is None:
                    pcp_text = "-"
                elif day.get("pcp"):
                    pcp_text = day.get("pcp")
                elif day.get("source") == "중기예보":
                    pcp_text = "중기예보만"
                else:
                    pcp_text = "강수없음"
                pcp_font = QFont(self.font_body)
                pcp_font.setBold(is_best)
                self._set_summary_item(table, row_idx, 5, pcp_text, emph_color, row_bg, pcp_font)

                warn_text = "⚠" if (report and report.get("warnings")) else ""
                self._set_summary_item(table, row_idx, 6, warn_text, c["warn_text"], row_bg, self.font_small)

                self._set_summary_item(table, row_idx, 0, "", c["text"], c["bg"], self.font_body)

                row_idx += 1

            branch_item = QTableWidgetItem(branch_name)
            branch_item.setForeground(_qcolor(c["text"]))
            branch_item.setBackground(_qcolor(c["bg"]))
            branch_item.setFont(self.font_body)
            branch_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(start_row, 0, branch_item)
            if row_idx - start_row > 1:
                table.setSpan(start_row, 0, row_idx - start_row, 1)
            for r in range(start_row, row_idx):
                self._summary_branch_rows[r] = (branch_name, list(members))

        table.resizeColumnsToContents()
        # 지사 열은 대부분 행이 span으로 합쳐져 실제 텍스트가 있는 행이 거의 없다보니
        # resizeColumnsToContents()가 내용을 제대로 못 읽고 너무 좁게(글자가 "..."로
        # 잘릴 정도로) 잡는 경우가 있어, 지사명이 넉넉히 들어갈 고정 너비로 보정한다.
        table.setColumnWidth(0, 90)

    @staticmethod
    def _set_summary_item(table, row, col, text, color_hex, bg_hex, font):
        item = QTableWidgetItem(text)
        item.setForeground(_qcolor(color_hex))
        item.setBackground(_qcolor(bg_hex))
        item.setFont(font)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter if col != 1 else Qt.AlignmentFlag.AlignVCenter)
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
