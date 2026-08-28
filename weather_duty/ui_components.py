"""Calm Operations Dashboard 순수 프레젠테이션 컴포넌트.

이 모듈의 위젯은 "보여주기"만 담당한다. 기상청 API 호출, config.json 저장,
스레드/시그널 배선 같은 비즈니스 로직은 절대 포함하지 않는다 - 호출부(gui.py)가
텍스트/상태 값을 만들어 넘겨주면 그 값을 theme.py의 토큰에 맞춰 어떻게
그릴지만 책임진다.

모든 컴포넌트는 생성 시점과 `set_*()` 호출 시점, 그리고 라이트/다크 모드가
바뀔 때 자기 스타일을 다시 계산한다. 앱 전체 QSS를 통째로 다시 만드는 대신
컴포넌트 각자가 자신의 작은 스타일시트만 갱신하고, 반복 생성/파괴될 수 있는
위젯이므로 테마 변경 구독은 `theme.bind_theme_change()`(위젯 파괴 시 자동
연결 해제)로 건다.
"""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from qfluentwidgets import TransparentToolButton

from . import theme

# 상태/톤 이름 -> (전경색 토큰, 배경색 토큰). 색상만으로 상태를 구분하지 않도록
# 호출부는 항상 문구(텍스트)를 함께 넘긴다는 전제로 설계되어 있다.
_TONE_ROLES = {
    "neutral": ("text_secondary", "surface_alt"),
    "loading": ("text_secondary", "surface_alt"),
    "accent": ("accent", "accent_soft"),
    "info": ("info", "info_soft"),
    "success": ("success", "success_soft"),
    "warning": ("warning", "warning_soft"),
    "danger": ("danger", "danger_soft"),
}

_BANNER_GLYPHS = {
    "info": "ℹ",
    "success": "✓",
    "warning": "⚠",
    "danger": "✕",
}


def _tone_colors(c, tone):
    fg_key, bg_key = _TONE_ROLES.get(tone, _TONE_ROLES["neutral"])
    return c[fg_key], c[bg_key]


class StatusPill(QWidget):
    """짧은 상태 배지(로딩/정상/주의/오류 등). 알약형이지만 항상 텍스트를 함께
    보여줘 색상만으로 상태를 구분하지 않는다."""

    def __init__(self, text="", tone="neutral", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._tone = tone

        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_1, theme.SPACE_3, theme.SPACE_1)
        layout.setSpacing(theme.SPACE_1)
        self._label = QLabel(text, self)
        self._label.setFont(theme.font_role("micro"))
        layout.addWidget(self._label)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self._refresh_style()
        theme.bind_theme_change(self, self._refresh_style)

    def set_state(self, text=None, tone=None):
        if text is not None:
            self._label.setText(text)
        if tone is not None:
            self._tone = tone
        self._refresh_style()

    def _refresh_style(self):
        c = theme.colors()
        fg, bg = _tone_colors(c, self._tone)
        theme.set_dynamic_property(self, "tone", self._tone)
        self.setStyleSheet(
            f"StatusPill {{ background-color:{bg}; border-radius:{theme.RADIUS_PILL}px; }}"
        )
        self._label.setStyleSheet(f"color:{fg}; background:transparent;")


class TagBadge(QLabel):
    """지사명, 데이터 출처(실측/단기예보/중기예보) 같은 짧은 분류 태그 한 줄짜리 라벨."""

    def __init__(self, text="", tone="neutral", parent=None):
        super().__init__(text, parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._tone = tone
        self.setFont(theme.font_role("micro"))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._refresh_style()
        theme.bind_theme_change(self, self._refresh_style)

    def set_tone(self, tone):
        self._tone = tone
        self._refresh_style()

    def set_text_and_tone(self, text, tone=None):
        self.setText(text)
        if tone is not None:
            self._tone = tone
        self._refresh_style()

    def _refresh_style(self):
        c = theme.colors()
        fg, bg = _tone_colors(c, self._tone)
        theme.set_dynamic_property(self, "tone", self._tone)
        self.setStyleSheet(
            f"TagBadge {{ color:{fg}; background-color:{bg};"
            f" border-radius:{theme.RADIUS_SMALL}px; padding:2px {theme.SPACE_2}px; }}"
        )


class InlineBanner(QWidget):
    """정보/정상/주의/오류 메시지를 배경색 + 접두 기호 + 텍스트로 보여주는 배너.
    상세보기의 특보 배너, 오류 문구처럼 흩어져 있던 "상태 배너" 패턴을 하나로
    표준화하기 위한 컴포넌트(레이아웃 배선은 gui.py가 그대로 담당)."""

    def __init__(self, text="", level="info", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._level = level

        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        layout.setSpacing(theme.SPACE_2)
        self._glyph_label = QLabel(self)
        self._glyph_label.setFont(theme.font_role("body_medium"))
        layout.addWidget(self._glyph_label)
        self._text_label = QLabel(text, self)
        self._text_label.setFont(theme.font_role("body"))
        self._text_label.setWordWrap(True)
        layout.addWidget(self._text_label, 1)

        self._refresh_style()
        theme.bind_theme_change(self, self._refresh_style)

    def set_message(self, text, level=None):
        self._text_label.setText(text)
        if level is not None:
            self._level = level
        self._refresh_style()

    def _refresh_style(self):
        c = theme.colors()
        fg, bg = _tone_colors(c, self._level)
        glyph = _BANNER_GLYPHS.get(self._level, _BANNER_GLYPHS["info"])
        theme.set_dynamic_property(self, "level", self._level)
        self._glyph_label.setText(glyph)
        self.setStyleSheet(
            f"InlineBanner {{ background-color:{bg}; border-radius:{theme.RADIUS_PANEL}px; }}"
        )
        self._glyph_label.setStyleSheet(f"color:{fg}; background:transparent;")
        self._text_label.setStyleSheet(f"color:{fg}; background:transparent;")


class SectionHeader(QWidget):
    """제목(+선택적 부제, +선택적 우측 액션 위젯) 한 줄을 표준화한 헤더.
    "지난 실측 2일 + 향후 예보", "날짜 선택" 같은 섹션 소제목 자리에 쓴다."""

    def __init__(self, title, subtitle=None, action_widget=None, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(theme.SPACE_1)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_3)
        self._title_label = QLabel(title, self)
        self._title_label.setFont(theme.font_role("section_title"))
        row.addWidget(self._title_label)
        row.addStretch(1)
        if action_widget is not None:
            row.addWidget(action_widget)
        outer.addLayout(row)

        self._subtitle_label = None
        if subtitle:
            self._subtitle_label = QLabel(subtitle, self)
            self._subtitle_label.setFont(theme.font_role("caption"))
            self._subtitle_label.setWordWrap(True)
            outer.addWidget(self._subtitle_label)

        self._refresh_style()
        theme.bind_theme_change(self, self._refresh_style)

    def set_title(self, title):
        self._title_label.setText(title)

    def set_subtitle(self, subtitle):
        # 생성 시 subtitle 없이 만들어졌으면 라벨 자체가 없어 자리도 없다.
        # 나중에 subtitle이 필요해지면 SectionHeader를 subtitle과 함께 다시 만든다.
        if self._subtitle_label is not None:
            self._subtitle_label.setText(subtitle or "")

    def _refresh_style(self):
        c = theme.colors()
        self._title_label.setStyleSheet(f"color:{c['text_primary']}; background:transparent;")
        if self._subtitle_label is not None:
            self._subtitle_label.setStyleSheet(f"color:{c['text_tertiary']}; background:transparent;")


class MetricBlock(QWidget):
    """현재 기온처럼 화면에서 가장 큰 핵심 수치 하나 + 짧은 캡션을 보여주는 블록."""

    def __init__(self, value_text="-", caption_text="", parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_1)
        self._value_label = QLabel(value_text, self)
        self._value_label.setFont(theme.font_role("metric_display"))
        layout.addWidget(self._value_label)
        self._caption_label = QLabel(caption_text, self)
        self._caption_label.setFont(theme.font_role("body"))
        layout.addWidget(self._caption_label)

        self._refresh_style()
        theme.bind_theme_change(self, self._refresh_style)

    def set_value(self, value_text):
        self._value_label.setText(value_text)

    def set_caption(self, caption_text):
        self._caption_label.setText(caption_text)

    def _refresh_style(self):
        c = theme.colors()
        self._value_label.setStyleSheet(f"color:{c['text_primary']}; background:transparent;")
        self._caption_label.setStyleSheet(f"color:{c['text_secondary']}; background:transparent;")


class EmptyState(QWidget):
    """즐겨찾기 없음/예보 없음/검색 결과 없음처럼 "보여줄 데이터가 없는" 상태를
    표준화한 안내 위젯. 제목 + 선택적 설명 문구를 가운데 정렬로 보여준다."""

    def __init__(self, title, description="", parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_8, theme.SPACE_8, theme.SPACE_8, theme.SPACE_8)
        layout.setSpacing(theme.SPACE_2)
        # 주의: 여기서 layout.setAlignment(Qt.AlignmentFlag.AlignCenter)를 쓰면 안 된다.
        # 이 PySide6/Pretendard 조합에서, 정렬이 걸린 QVBoxLayout 안에 줄바꿈되는
        # QLabel이 있으면 그 줄바꿈된 텍스트가 뒤집혀서(상하좌우 반전) 그려지는
        # 렌더링 버그가 실제로 재현된다(오프스크린·실제 xcb 렌더링 모두 동일).
        # 대신 앞뒤로 stretch를 넣어 수직 가운데 정렬 효과만 얻는다.
        layout.addStretch(1)

        self._title_label = QLabel(title, self)
        self._title_label.setFont(theme.font_role("card_title"))
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._title_label)

        # description 없이 만들어져도 나중에 set_description()으로 채울 수 있도록
        # 라벨은 항상 만들어 두고, 텍스트가 비어 있을 때만 숨긴다.
        self._desc_label = QLabel(description, self)
        self._desc_label.setFont(theme.font_role("caption"))
        self._desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._desc_label.setWordWrap(True)
        self._desc_label.setVisible(bool(description))
        layout.addWidget(self._desc_label)

        layout.addStretch(1)

        self._refresh_style()
        theme.bind_theme_change(self, self._refresh_style)

    def set_title(self, title):
        self._title_label.setText(title)

    def set_description(self, description):
        self._desc_label.setText(description)
        self._desc_label.setVisible(bool(description))

    def _refresh_style(self):
        c = theme.colors()
        self._title_label.setStyleSheet(f"color:{c['text_secondary']}; background:transparent;")
        self._desc_label.setStyleSheet(f"color:{c['text_tertiary']}; background:transparent;")


class IconActionButton(TransparentToolButton):
    """아이콘 전용 액션 버튼을 표준 크기(CONTROL_HEIGHT_SMALL)·아이콘 크기로
    감싼다. 크기를 고정해 hover/pressed로 레이아웃이 흔들리지 않게 한다."""

    def __init__(self, icon, tooltip="", parent=None):
        # TransparentToolButton(icon, parent)의 singledispatch 생성자는 내부에서
        # self.__init__(parent)를 다시 호출하는데, self가 이 서브클래스 인스턴스라
        # 그 재호출이 (부모가 아니라) 이 __init__으로 되돌아와 인자 개수가 꼬인다.
        # 그래서 부모 없이(parent만) 생성한 뒤 setIcon()을 직접 호출한다.
        super().__init__(parent)
        self.setIcon(icon)
        self.setFixedSize(theme.CONTROL_HEIGHT_SMALL, theme.CONTROL_HEIGHT_SMALL)
        self.setIconSize(QSize(theme.ICON_SIZE_DEFAULT, theme.ICON_SIZE_DEFAULT))
        if tooltip:
            self.setToolTip(tooltip)


class ForecastRow(QFrame):
    """일자별 예보 한 줄(지역별 상세보기). 순수 표시 컴포넌트 - 호출부(gui.py)가
    이미 계산/포맷을 끝낸 문자열과 톤 이름만 `set_data()`로 넘겨받아 배치할
    뿐, API 호출이나 수치 계산·재해석은 하지 않는다.

    정보 배치(넓은 화면 기준): [날짜/요일] [날씨 상태] [강수확률] [강수량]
    [체감] [출처 배지] [최저/최고] [chevron]. QGridLayout + stretch factor로
    배치해 넓은 화면에서 늘어나고 좁은 화면에서도 주요 수치가 겹치지 않게 한다."""

    doubleClicked = Signal()

    _COL_DATE, _COL_CONDITION, _COL_POP, _COL_PCP, _COL_FEELS, _COL_SOURCE, _COL_TEMP, _COL_CHEVRON = range(8)

    # 강수량 배지는 "중기예보(강수량 미제공)"처럼 유독 긴 문구가 나올 수 있어,
    # 이 칸만 최대 폭을 두고 넘치면 말줄임(...) + 툴팁으로 전체 문구를 보여준다
    # (8칸짜리 좁은 행에서 이 배지 하나 때문에 960px에서도 잘리는 걸 막기 위함).
    _PCP_BADGE_MAX_WIDTH = 108

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(theme.FORECAST_ROW_HEIGHT)

        grid = QGridLayout(self)
        grid.setContentsMargins(theme.SPACE_3, 0, theme.SPACE_3, 0)
        grid.setHorizontalSpacing(theme.SPACE_2)

        self._date_label = QLabel(self)
        self._date_label.setFont(theme.font_role("caption"))
        grid.addWidget(self._date_label, 0, self._COL_DATE)

        self._condition_label = QLabel(self)
        self._condition_label.setFont(theme.font_role("body"))
        grid.addWidget(self._condition_label, 0, self._COL_CONDITION)

        self._pop_badge = TagBadge("", tone="neutral", parent=self)
        grid.addWidget(self._pop_badge, 0, self._COL_POP, Qt.AlignmentFlag.AlignVCenter)

        self._pcp_badge = TagBadge("", tone="neutral", parent=self)
        self._pcp_badge.setMaximumWidth(self._PCP_BADGE_MAX_WIDTH)
        grid.addWidget(self._pcp_badge, 0, self._COL_PCP, Qt.AlignmentFlag.AlignVCenter)

        self._feels_label = QLabel(self)
        self._feels_label.setFont(theme.font_role("caption"))
        grid.addWidget(self._feels_label, 0, self._COL_FEELS)

        self._source_badge = TagBadge("", tone="neutral", parent=self)
        self._source_badge.setFixedHeight(theme.SPACE_6 - theme.SPACE_1)  # 22~24px
        grid.addWidget(self._source_badge, 0, self._COL_SOURCE, Qt.AlignmentFlag.AlignVCenter)

        self._temp_label = QLabel(self)
        self._temp_label.setFont(theme.font_role("label"))
        self._temp_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(self._temp_label, 0, self._COL_TEMP)

        self._chevron_label = QLabel("›", self)
        self._chevron_label.setFont(theme.font_role("card_title"))
        self._chevron_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self._chevron_label, 0, self._COL_CHEVRON)

        # 날씨 상태(condition) 칸만 남는 공간을 가져가고, 나머지는 내용 크기만큼만
        # 차지한다 - 고정 폭을 여러 칸에 걸어두는 대신 이 칸 하나에만 stretch를 준다.
        grid.setColumnStretch(self._COL_CONDITION, 1)

        self._refresh_style()
        theme.bind_theme_change(self, self._refresh_style)

    def set_data(
        self, *, date_text, condition_text, pop_text, pop_tone, pcp_text,
        feels_text, source_text, source_tone, temp_text, tooltip,
    ):
        """이미 계산된 표시 문자열만 받는다 - 여기서 숫자를 새로 계산하지 않는다."""
        self._date_label.setText(date_text)
        self._condition_label.setText(condition_text)
        self._pop_badge.set_text_and_tone(pop_text, pop_tone)
        # 뱃지 폭(패딩 포함)에 맞춰 필요할 때만 말줄임 - 원본 문구는 툴팁으로 유지.
        available = self._PCP_BADGE_MAX_WIDTH - theme.SPACE_2 * 2 - theme.SPACE_1
        elided_pcp = QFontMetrics(self._pcp_badge.font()).elidedText(
            pcp_text, Qt.TextElideMode.ElideRight, max(available, 0)
        )
        self._pcp_badge.set_text_and_tone(elided_pcp, "neutral")
        self._pcp_badge.setToolTip(pcp_text)
        self._feels_label.setText(feels_text)
        self._feels_label.setVisible(bool(feels_text))
        self._source_badge.set_text_and_tone(source_text, source_tone)
        self._temp_label.setText(temp_text)
        self.setToolTip(tooltip)

    def mouseDoubleClickEvent(self, event):  # noqa: N802 - Qt override
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)

    def _refresh_style(self):
        c = theme.colors()
        self.setStyleSheet(
            f"ForecastRow {{ background-color:transparent; border-radius:{theme.RADIUS_CONTROL}px; }}"
            f"ForecastRow:hover {{ background-color:{c['surface_hover']}; }}"
        )
        for label, color_key in (
            (self._date_label, "text_primary"),
            (self._condition_label, "text_secondary"),
            (self._feels_label, "text_primary"),
            (self._temp_label, "text_primary"),
            (self._chevron_label, "text_tertiary"),
        ):
            label.setStyleSheet(f"color:{c[color_key]}; background:transparent;")
