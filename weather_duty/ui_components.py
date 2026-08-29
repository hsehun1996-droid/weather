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
import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QStackedLayout, QVBoxLayout, QWidget,
)

from qfluentwidgets import FluentIcon, IndeterminateProgressRing, TransparentToolButton

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
        self.setAccessibleName(text)

        self._refresh_style()
        theme.bind_theme_change(self, self._refresh_style)

    def set_state(self, text=None, tone=None):
        if text is not None:
            self._label.setText(text)
            self.setAccessibleName(text)
        if tone is not None:
            self._tone = tone
        self._refresh_style()

    def _refresh_style(self):
        c = theme.colors()
        fg, bg = _tone_colors(c, self._tone)
        theme.set_dynamic_property(self, "tone", self._tone)
        self.setStyleSheet(
            f"StatusPill {{ background-color:{bg}; border:none; border-radius:{theme.RADIUS_PILL}px; }}"
        )
        self._label.setStyleSheet(f"color:{fg}; background:transparent; border:none;")


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
            f"TagBadge {{ color:{fg}; background-color:{bg}; border:none;"
            f" border-radius:{theme.RADIUS_SMALL}px; padding:2px {theme.SPACE_2}px; }}"
        )


class InlineBanner(QWidget):
    """정보/정상/주의/오류 메시지를 배경색 + 접두 기호 + 텍스트로 보여주는 배너.
    상세보기의 특보 배너, 오류 문구처럼 흩어져 있던 "상태 배너" 패턴을 하나로
    표준화하기 위한 컴포넌트(레이아웃 배선은 gui.py가 그대로 담당).

    title(선택)을 주면 굵은 제목 줄이 본문 위에 붙는다("데이터 조회 오류"
    처럼). subtle=True는 "특보 없음"처럼 평상시 상태를 나타낼 때 쓴다 -
    톤 배경(예: success_soft) 대신 surface_alt로 덜 튀게 칠하고 본문 글자도
    중립색(text_secondary)을 써서 초록 등을 과하게 쓰지 않는다."""

    def __init__(self, text="", level="info", parent=None, title=None, subtle=False):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._level = level
        self._subtle = subtle

        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        layout.setSpacing(theme.SPACE_2)
        self._glyph_label = QLabel(self)
        self._glyph_label.setFont(theme.font_role("body_medium"))
        layout.addWidget(self._glyph_label, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(theme.SPACE_1)
        self._title_label = QLabel(self)
        self._title_label.setFont(theme.font_role("label"))
        self._title_label.setWordWrap(True)
        self._title_label.setVisible(bool(title))
        if title:
            self._title_label.setText(title)
        text_col.addWidget(self._title_label)

        self._text_label = QLabel(text, self)
        self._text_label.setFont(theme.font_role("body"))
        self._text_label.setWordWrap(True)
        text_col.addWidget(self._text_label)
        layout.addLayout(text_col, 1)

        self.setAccessibleDescription(text)
        self._refresh_style()
        theme.bind_theme_change(self, self._refresh_style)

    @property
    def text_label(self):
        """본문 QLabel 자체를 노출한다 - gui.py가 self.error_label/
        self.warning_banner 같은 기존 속성명을 이 라벨의 alias로 유지해야
        해서 필요하다(그 외에는 set_message()를 쓰는 편이 낫다)."""
        return self._text_label

    def set_message(self, text, level=None):
        self._text_label.setText(text)
        self.setAccessibleDescription(text)
        if level is not None:
            self._level = level
        self._refresh_style()

    def set_title(self, title):
        self._title_label.setText(title or "")
        self._title_label.setVisible(bool(title))

    def set_level(self, level, subtle=None):
        self._level = level
        if subtle is not None:
            self._subtle = subtle
        self._refresh_style()

    def _refresh_style(self):
        c = theme.colors()
        fg, bg = _tone_colors(c, self._level)
        glyph = _BANNER_GLYPHS.get(self._level, _BANNER_GLYPHS["info"])
        body_color = fg
        if self._subtle:
            bg = c["surface_alt"]
            body_color = c["text_secondary"]
        theme.set_dynamic_property(self, "level", self._level)
        self._glyph_label.setText(glyph)
        self.setStyleSheet(
            f"InlineBanner {{ background-color:{bg}; border:none; border-radius:{theme.RADIUS_PANEL}px; }}"
        )
        self._glyph_label.setStyleSheet(f"color:{fg}; background:transparent; border:none;")
        self._title_label.setStyleSheet(f"color:{fg}; background:transparent; border:none;")
        self._text_label.setStyleSheet(f"color:{body_color}; background:transparent; border:none;")


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
        self._title_label.setStyleSheet(f"color:{c['text_primary']}; background:transparent; border:none;")
        if self._subtitle_label is not None:
            self._subtitle_label.setStyleSheet(f"color:{c['text_tertiary']}; background:transparent; border:none;")


class MetricBlock(QWidget):
    """핵심 수치 하나 + 짧은 캡션을 보여주는 블록. 기본값(metric_display, 42px)은
    Hero의 "현재 기온"처럼 화면에서 가장 큰 핵심 수치용이고, 다이얼로그 안의
    작은 요약 수치 여러 개를 나란히 두는 자리에서는 value_font_role로 더 작은
    역할(예: "card_title")을 줄 수 있다."""

    def __init__(self, value_text="-", caption_text="", parent=None, value_font_role="metric_display"):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_1)
        self._value_label = QLabel(value_text, self)
        self._value_label.setFont(theme.font_role(value_font_role))
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
        self._value_label.setStyleSheet(f"color:{c['text_primary']}; background:transparent; border:none;")
        self._caption_label.setStyleSheet(f"color:{c['text_secondary']}; background:transparent; border:none;")


class EmptyState(QWidget):
    """즐겨찾기 없음/예보 없음/검색 결과 없음처럼 "보여줄 데이터가 없는" 상태를
    표준화한 안내 위젯. 제목 + 선택적 설명 문구를 가운데 정렬로 보여준다.

    tone="warning"(서비스키 미설정처럼 조치가 필요한 상태)을 주면 옅은
    warning_soft 배경을 두르고, action_widget(예: "설정 열기" 버튼)을 주면
    설명 아래 가운데 정렬로 붙는다 - 기본값(tone="neutral", action_widget=None)일
    때는 이전과 완전히 동일하게 그려진다(기존 호출부 영향 없음)."""

    def __init__(self, title, description="", parent=None, tone="neutral", action_widget=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._tone = tone

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
        self._title_label.setWordWrap(True)
        layout.addWidget(self._title_label)

        # description 없이 만들어져도 나중에 set_description()으로 채울 수 있도록
        # 라벨은 항상 만들어 두고, 텍스트가 비어 있을 때만 숨긴다.
        self._desc_label = QLabel(description, self)
        self._desc_label.setFont(theme.font_role("caption"))
        self._desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._desc_label.setWordWrap(True)
        self._desc_label.setVisible(bool(description))
        layout.addWidget(self._desc_label)

        self._action_row = QHBoxLayout()
        self._action_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._action_row.setContentsMargins(0, theme.SPACE_1, 0, 0)
        layout.addLayout(self._action_row)
        self._action_widget = None
        if action_widget is not None:
            self.set_action_widget(action_widget)

        layout.addStretch(1)

        self._refresh_style()
        theme.bind_theme_change(self, self._refresh_style)

    def set_title(self, title):
        self._title_label.setText(title)

    def set_description(self, description):
        self._desc_label.setText(description)
        self._desc_label.setVisible(bool(description))

    def set_tone(self, tone):
        self._tone = tone
        self._refresh_style()

    def set_action_widget(self, widget):
        if self._action_widget is not None:
            self._action_row.removeWidget(self._action_widget)
            self._action_widget.setParent(None)
            self._action_widget.deleteLater()
        self._action_widget = widget
        if widget is not None:
            self._action_row.addWidget(widget)

    def _refresh_style(self):
        c = theme.colors()
        if self._tone == "warning":
            self.setStyleSheet(
                f"EmptyState {{ background-color:{c['warning_soft']}; border:none; border-radius:{theme.RADIUS_PANEL}px; }}"
            )
            title_color, desc_color = c["text_primary"], c["text_secondary"]
        else:
            self.setStyleSheet("EmptyState { background-color:transparent; }")
            title_color, desc_color = c["text_secondary"], c["text_tertiary"]
        self._title_label.setStyleSheet(f"color:{title_color}; background:transparent; border:none;")
        self._desc_label.setStyleSheet(f"color:{desc_color}; background:transparent; border:none;")


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
            self.setAccessibleName(tooltip)


class DangerHoverIconButton(TransparentToolButton):
    """삭제류 아이콘 버튼: 평소엔 text_secondary, 마우스가 올라가 있는 동안만
    danger 톤으로 바뀐다("삭제 아이콘을 항상 밝은 빨간색으로" 두지 않기 위함).
    qfluentwidgets FluentIconBase.colored()로 두 가지 고정색 아이콘을 미리
    만들어 두고 enter/leave에서 맞바꾸는 방식이라 새 애니메이션·패키지가 없다."""

    def __init__(self, icon, tooltip="", parent=None):
        super().__init__(parent)
        self._icon = icon
        self.setFixedSize(theme.CONTROL_HEIGHT_SMALL, theme.CONTROL_HEIGHT_SMALL)
        self.setIconSize(QSize(theme.ICON_SIZE_DEFAULT, theme.ICON_SIZE_DEFAULT))
        if tooltip:
            self.setToolTip(tooltip)
            self.setAccessibleName(tooltip)
        self._normal_icon = icon
        self._danger_icon = icon
        self._refresh_icons()
        theme.bind_theme_change(self, self._refresh_icons)

    def _refresh_icons(self):
        c = theme.colors()
        self._normal_icon = self._icon.colored(c["text_secondary"], c["text_secondary"])
        self._danger_icon = self._icon.colored(c["danger"], c["danger"])
        self.setIcon(self._normal_icon)

    def enterEvent(self, event):  # noqa: N802 - Qt override
        self.setIcon(self._danger_icon)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802 - Qt override
        self.setIcon(self._normal_icon)
        super().leaveEvent(event)


class LoadingState(QWidget):
    """"조회 중" 상태를 표준화한 위젯. 반복 pulse/shimmer 같은 무거운 효과 대신
    qfluentwidgets의 작은 회전 인디케이터(IndeterminateProgressRing) 하나 +
    문구만 쓴다. EmptyState와 같은 규칙(stretch로 수직 중앙 정렬)을 따른다."""

    def __init__(self, title="기상 정보를 조회하고 있습니다.", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_8, theme.SPACE_8, theme.SPACE_8, theme.SPACE_8)
        layout.setSpacing(theme.SPACE_3)
        layout.addStretch(1)

        ring_row = QHBoxLayout()
        ring_row.addStretch(1)
        self._ring = IndeterminateProgressRing(self)
        self._ring.setFixedSize(28, 28)
        self._ring.setStrokeWidth(3)
        ring_row.addWidget(self._ring)
        ring_row.addStretch(1)
        layout.addLayout(ring_row)

        self._title_label = QLabel(title, self)
        self._title_label.setFont(theme.font_role("card_title"))
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setWordWrap(True)
        layout.addWidget(self._title_label)

        layout.addStretch(1)

        self._refresh_style()
        theme.bind_theme_change(self, self._refresh_style)

    def set_title(self, title):
        self._title_label.setText(title)

    def _refresh_style(self):
        c = theme.colors()
        self.setStyleSheet("LoadingState { background-color:transparent; }")
        self._title_label.setStyleSheet(f"color:{c['text_secondary']}; background:transparent; border:none;")


class DialogHeader(QWidget):
    """다이얼로그 상단 제목(18~20px DemiBold) + 짧은 설명(caption, text_secondary,
    4~6px 간격) 표준 헤더. 본문 섹션 소제목(SectionHeader, text_tertiary 부제)과는
    다이얼로그 전용으로 별도 규격을 쓴다 - 기존 SectionHeader 용법에는 영향 없다."""

    def __init__(self, title, description="", parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_1)  # 4px (spec 허용 범위 4~6px)

        self._title_label = QLabel(title, self)
        self._title_label.setFont(theme.font_role("section_title"))
        self._title_label.setWordWrap(True)
        layout.addWidget(self._title_label)

        self._desc_label = QLabel(description, self)
        self._desc_label.setFont(theme.font_role("caption"))
        self._desc_label.setWordWrap(True)
        self._desc_label.setVisible(bool(description))
        layout.addWidget(self._desc_label)

        self._refresh_style()
        theme.bind_theme_change(self, self._refresh_style)

    def set_title(self, title):
        self._title_label.setText(title)

    def set_description(self, description):
        self._desc_label.setText(description)
        self._desc_label.setVisible(bool(description))

    def _refresh_style(self):
        c = theme.colors()
        self._title_label.setStyleSheet(f"color:{c['text_primary']}; background:transparent; border:none;")
        self._desc_label.setStyleSheet(f"color:{c['text_secondary']}; background:transparent; border:none;")


class DialogFooter(QWidget):
    """다이얼로그 하단 버튼 줄 표준 레이아웃: 선택적 상단 divider + 우측 정렬
    버튼들(8px 간격). 버튼은 호출부(gui.py)가 이미 만들어 콜백까지 연결해
    넘긴다 - 이 위젯은 배치만 책임진다."""

    def __init__(self, buttons, with_divider=True, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(theme.SPACE_3)

        self._divider = None
        if with_divider:
            self._divider = QFrame(self)
            self._divider.setFixedHeight(1)
            outer.addWidget(self._divider)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_2)
        row.addStretch(1)
        for btn in buttons:
            row.addWidget(btn)
        outer.addLayout(row)

        self._refresh_style()
        theme.bind_theme_change(self, self._refresh_style)

    def _refresh_style(self):
        if self._divider is not None:
            c = theme.colors()
            self._divider.setStyleSheet(f"background-color:{c['divider']};")


class FormField(QWidget):
    """label + 입력 위젯 + helper/오류 텍스트 한 줄을 표준 규격으로 쌓는다.
    입력 위젯(LineEdit/ComboBox 등)은 호출부가 만들어 넘긴다 - 검증 규칙과
    값 처리는 이 위젯이 알지 못하며, 오직 "표시"만 담당한다.

    set_error(message)를 부르면 helper 텍스트 자리가 그 메시지로 바뀌고
    (기존 helper_text는 오류가 없어지면 clear_error()로 복원), 입력 위젯이
    qfluentwidgets의 setError()를 지원하면 그것도 함께 켠다 - 필드 높이는
    항상 label+입력+helper 한 줄 구조라 오류 표시로 레이아웃이 크게 흔들리지
    않는다."""

    def __init__(self, label_text, input_widget, helper_text="", required=False, parent=None):
        super().__init__(parent)
        self._helper_text = helper_text
        self._is_error = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_1)

        label_row = QHBoxLayout()
        label_row.setContentsMargins(0, 0, 0, 0)
        label_row.setSpacing(2)
        self._label = QLabel(label_text, self)
        self._label.setFont(theme.font_role("label"))
        label_row.addWidget(self._label)
        self._required_mark = None
        if required:
            self._required_mark = QLabel("*", self)
            self._required_mark.setFont(theme.font_role("label"))
            label_row.addWidget(self._required_mark)
        label_row.addStretch(1)
        layout.addLayout(label_row)

        self._input_widget = input_widget
        layout.addWidget(input_widget)

        self._helper_label = QLabel(helper_text, self)
        self._helper_label.setFont(theme.font_role("caption"))
        self._helper_label.setWordWrap(True)
        self._helper_label.setVisible(bool(helper_text))
        layout.addWidget(self._helper_label)

        self._refresh_style()
        theme.bind_theme_change(self, self._refresh_style)

    def set_error(self, message):
        self._is_error = bool(message)
        if message:
            self._helper_label.setText(message)
            self._helper_label.setVisible(True)
        else:
            self._helper_label.setText(self._helper_text)
            self._helper_label.setVisible(bool(self._helper_text))
        if hasattr(self._input_widget, "setError"):
            self._input_widget.setError(self._is_error)
        self._refresh_style()

    def clear_error(self):
        self.set_error(None)

    def _refresh_style(self):
        c = theme.colors()
        self._label.setStyleSheet(f"color:{c['text_primary']}; background:transparent; border:none;")
        if self._required_mark is not None:
            self._required_mark.setStyleSheet(f"color:{c['danger']}; background:transparent; border:none;")
        helper_color = c["danger"] if self._is_error else c["text_tertiary"]
        self._helper_label.setStyleSheet(f"color:{helper_color}; background:transparent; border:none;")


def _draw_weather_icon_pixmap(condition_text, color_hex, size=16):
    """condition 문자열(API 값 그대로, 재해석하지 않고 부분 문자열 매칭만
    한다)에 맞춰 아주 단순한 단색 QPainter 아이콘을 그린다. 컬러 이모지나
    외부 아이콘/폰트 없이, 라이트/다크 갱신 시 색만 바꿔 다시 그릴 수 있게
    순수 벡터로 그린다 - 텍스트는 절대 대체하지 않고 옆에 나란히 쓴다."""
    condition_text = condition_text or ""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color_hex))
    pen.setWidthF(1.3)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    has_rain = "비" in condition_text
    has_snow = "눈" in condition_text
    is_clear = "맑음" in condition_text and not has_rain and not has_snow
    cx, cy = size / 2.0, size / 2.0

    if is_clear:
        r = size * 0.24
        painter.drawEllipse(QPointF(cx, cy), r, r)
        for angle in range(0, 360, 45):
            rad = math.radians(angle)
            x1, y1 = cx + (r + 1.5) * math.cos(rad), cy + (r + 1.5) * math.sin(rad)
            x2, y2 = cx + (r + 4) * math.cos(rad), cy + (r + 4) * math.sin(rad)
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    elif condition_text:
        # 구름 모양(둥근 사각형 + 위로 볼록한 원 두 개) - 흐림/구름/비/눈 공통 베이스.
        cloud_w, cloud_h = size * 0.8, size * 0.36
        cloud_rect = QRectF(cx - cloud_w / 2, cy - cloud_h * 0.25, cloud_w, cloud_h)
        painter.drawRoundedRect(cloud_rect, cloud_h / 2, cloud_h / 2)
        painter.drawEllipse(QPointF(cx - cloud_w * 0.16, cy - cloud_h * 0.35), cloud_h * 0.4, cloud_h * 0.4)
        painter.drawEllipse(QPointF(cx + cloud_w * 0.14, cy - cloud_h * 0.55), cloud_h * 0.46, cloud_h * 0.46)
        base_y = cy + cloud_h * 0.2
        if has_rain:
            for dx in (-cloud_w * 0.22, 0.0, cloud_w * 0.22):
                painter.drawLine(QPointF(cx + dx, base_y + 1), QPointF(cx + dx - 1, base_y + size * 0.28))
        if has_snow:
            for dx in (-cloud_w * 0.22, 0.0, cloud_w * 0.22):
                py = base_y + size * 0.2
                painter.drawLine(QPointF(cx + dx - 1.2, py), QPointF(cx + dx + 1.2, py))
                painter.drawLine(QPointF(cx + dx, py - 1.2), QPointF(cx + dx, py + 1.2))
    else:
        # 알 수 없음/데이터 없음 - 옅은 원 하나만(과한 강조 없는 중립 fallback).
        r = size * 0.22
        painter.drawEllipse(QPointF(cx, cy), r, r)
    painter.end()
    return pixmap


class ForecastRow(QFrame):
    """일자별 예보 한 줄(지역별 상세보기). 순수 표시 컴포넌트 - 호출부(gui.py)가
    이미 계산/포맷을 끝낸 문자열과 톤 이름만 `set_data()`로 넘겨받아 배치할
    뿐, API 호출이나 수치 계산·재해석은 하지 않는다.

    콘텐츠 폭이 FORECAST_ROW_COMPACT_BREAKPOINT(760px) 이상이면 한 줄(normal),
    미만이면 두 줄(compact) 레이아웃으로 전환한다 - 정보를 숨기거나 가로
    스크롤을 만드는 대신 항상 미리 만들어 둔 두 레이아웃 중 하나만 보여주는
    방식(QStackedLayout)이라, resizeEvent마다 위젯을 새로 만들지 않는다."""

    doubleClicked = Signal()
    activated = Signal()

    # 강수량 배지는 "중기예보(강수량 미제공)"처럼 유독 긴 문구가 나올 수 있어,
    # 이 칸만 최대 폭을 두고 넘치면 말줄임(...) + 툴팁으로 전체 문구를 보여준다.
    _PCP_BADGE_MAX_WIDTH = 108

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._has_detail = True
        self._is_compact = False

        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._normal = self._build_normal_page()
        self._compact = self._build_compact_page()
        self._stack.addWidget(self._normal["page"])
        self._stack.addWidget(self._compact["page"])
        self._apply_mode(compact=False)

        self._refresh_style()
        theme.bind_theme_change(self, self._refresh_style)

    # ---------- 레이아웃 생성 ----------
    def _make_icon_label(self, parent):
        label = QLabel(parent)
        label.setFixedSize(theme.ICON_SIZE_SMALL, theme.ICON_SIZE_SMALL)
        return label

    def _make_detail_button(self, parent, tooltip_text):
        btn = IconActionButton(FluentIcon.CHEVRON_RIGHT, tooltip=tooltip_text, parent=parent)
        btn.clicked.connect(self._on_detail_button_clicked)
        return btn

    def _build_normal_page(self):
        page = QWidget(self)
        grid = QGridLayout(page)
        grid.setContentsMargins(theme.SPACE_3, 0, theme.SPACE_3, 0)
        grid.setHorizontalSpacing(theme.SPACE_2)
        col_date, col_icon, col_cond, col_pop, col_pcp, col_feels, col_source, col_temp, col_btn = range(9)

        date_label = QLabel(page)
        date_label.setFont(theme.font_role("caption"))
        grid.addWidget(date_label, 0, col_date)

        icon_label = self._make_icon_label(page)
        grid.addWidget(icon_label, 0, col_icon, Qt.AlignmentFlag.AlignVCenter)

        condition_label = QLabel(page)
        condition_label.setFont(theme.font_role("body"))
        grid.addWidget(condition_label, 0, col_cond)

        pop_badge = TagBadge("", tone="neutral", parent=page)
        grid.addWidget(pop_badge, 0, col_pop, Qt.AlignmentFlag.AlignVCenter)

        pcp_badge = TagBadge("", tone="neutral", parent=page)
        pcp_badge.setMaximumWidth(self._PCP_BADGE_MAX_WIDTH)
        grid.addWidget(pcp_badge, 0, col_pcp, Qt.AlignmentFlag.AlignVCenter)

        feels_label = QLabel(page)
        feels_label.setFont(theme.font_role("caption"))
        grid.addWidget(feels_label, 0, col_feels)

        source_badge = TagBadge("", tone="neutral", parent=page)
        source_badge.setFixedHeight(theme.SPACE_6 - theme.SPACE_1)
        grid.addWidget(source_badge, 0, col_source, Qt.AlignmentFlag.AlignVCenter)

        temp_label = QLabel(page)
        temp_label.setFont(theme.font_role("label"))
        temp_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(temp_label, 0, col_temp)

        detail_btn = self._make_detail_button(page, "상세보기")
        grid.addWidget(detail_btn, 0, col_btn, Qt.AlignmentFlag.AlignVCenter)

        grid.setColumnStretch(col_cond, 1)

        return {
            "page": page, "date": date_label, "icon": icon_label, "condition": condition_label,
            "pop": pop_badge, "pcp": pcp_badge, "feels": feels_label, "source": source_badge,
            "temp": temp_label, "button": detail_btn,
        }

    def _build_compact_page(self):
        page = QWidget(self)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(theme.SPACE_3, theme.SPACE_1, theme.SPACE_3, theme.SPACE_1)
        outer.setSpacing(theme.SPACE_1)

        top_row = QHBoxLayout()
        top_row.setSpacing(theme.SPACE_2)
        date_label = QLabel(page)
        date_label.setFont(theme.font_role("caption"))
        top_row.addWidget(date_label)
        icon_label = self._make_icon_label(page)
        top_row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
        condition_label = QLabel(page)
        condition_label.setFont(theme.font_role("body"))
        top_row.addWidget(condition_label, 1)
        temp_label = QLabel(page)
        temp_label.setFont(theme.font_role("label"))
        temp_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top_row.addWidget(temp_label)
        detail_btn = self._make_detail_button(page, "상세보기")
        top_row.addWidget(detail_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(top_row)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(theme.SPACE_2)
        pop_badge = TagBadge("", tone="neutral", parent=page)
        bottom_row.addWidget(pop_badge)
        pcp_badge = TagBadge("", tone="neutral", parent=page)
        pcp_badge.setMaximumWidth(self._PCP_BADGE_MAX_WIDTH)
        bottom_row.addWidget(pcp_badge)
        feels_label = QLabel(page)
        feels_label.setFont(theme.font_role("caption"))
        bottom_row.addWidget(feels_label)
        bottom_row.addStretch(1)
        source_badge = TagBadge("", tone="neutral", parent=page)
        source_badge.setFixedHeight(theme.SPACE_6 - theme.SPACE_1)
        bottom_row.addWidget(source_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(bottom_row)

        return {
            "page": page, "date": date_label, "icon": icon_label, "condition": condition_label,
            "pop": pop_badge, "pcp": pcp_badge, "feels": feels_label, "source": source_badge,
            "temp": temp_label, "button": detail_btn,
        }

    # ---------- 데이터 반영 ----------
    def set_data(
        self, *, date_text, condition_text, pop_text, pop_tone, pcp_text,
        feels_text, source_text, source_tone, temp_text, tooltip, pcp_tooltip=None,
        has_detail=True, disabled_reason="",
    ):
        """이미 계산된 표시 문자열만 받는다 - 여기서 숫자를 새로 계산하지 않는다.
        pcp_tooltip을 안 주면(기존 호출부 호환) 기존처럼 pcp_text 전체를
        tooltip으로 쓴다. has_detail=False면 상세보기 버튼/키보드 활성화를
        비활성화하고 disabled_reason을 tooltip으로 보여준다(실제 시간별
        데이터가 없는 행)."""
        self._has_detail = has_detail
        available = self._PCP_BADGE_MAX_WIDTH - theme.SPACE_2 * 2 - theme.SPACE_1
        icon_color = theme.colors()["text_secondary"]

        for page in (self._normal, self._compact):
            page["date"].setText(date_text)
            page["condition"].setText(condition_text)
            page["icon"].setPixmap(_draw_weather_icon_pixmap(condition_text, icon_color, theme.ICON_SIZE_SMALL))
            page["pop"].set_text_and_tone(pop_text, pop_tone)
            elided_pcp = QFontMetrics(page["pcp"].font()).elidedText(
                pcp_text, Qt.TextElideMode.ElideRight, max(available, 0)
            )
            page["pcp"].set_text_and_tone(elided_pcp, "neutral")
            page["pcp"].setToolTip(pcp_tooltip if pcp_tooltip else pcp_text)
            page["feels"].setText(feels_text)
            page["feels"].setVisible(bool(feels_text))
            page["source"].set_text_and_tone(source_text, source_tone)
            page["temp"].setText(temp_text)

            btn = page["button"]
            btn.setVisible(True)
            btn.setEnabled(has_detail)
            btn_tip = "상세보기" if has_detail else (disabled_reason or "시간별 상세 데이터가 없습니다.")
            btn.setToolTip(btn_tip)
            btn.setAccessibleName(btn_tip)

        self.setToolTip(tooltip)
        self.setAccessibleName(f"{date_text} {condition_text} {temp_text}".strip())
        access_desc = tooltip or ("더블클릭 또는 상세보기 버튼으로 시간별 상세보기" if has_detail else "시간별 상세 데이터 없음")
        self.setAccessibleDescription(access_desc)

    # ---------- 반응형 전환 ----------
    def resizeEvent(self, event):  # noqa: N802 - Qt override
        super().resizeEvent(event)
        width = self.contentsRect().width()
        self._apply_mode(compact=width < theme.FORECAST_ROW_COMPACT_BREAKPOINT)

    def _apply_mode(self, compact):
        if compact == self._is_compact and self.height() in (
            theme.FORECAST_ROW_HEIGHT, theme.FORECAST_ROW_HEIGHT_COMPACT,
        ):
            # 이미 같은 모드면 다시 전환할 필요 없음(불필요한 재적용/깜박임 방지).
            if self._stack.currentWidget() is (self._compact["page"] if compact else self._normal["page"]):
                return
        self._is_compact = compact
        if compact:
            self._stack.setCurrentWidget(self._compact["page"])
            self.setMinimumHeight(theme.FORECAST_ROW_HEIGHT_COMPACT)
            self.setMaximumHeight(theme.FORECAST_ROW_HEIGHT_COMPACT)
        else:
            self._stack.setCurrentWidget(self._normal["page"])
            self.setMinimumHeight(theme.FORECAST_ROW_HEIGHT)
            self.setMaximumHeight(theme.FORECAST_ROW_HEIGHT)

    # ---------- 활성화(더블클릭/버튼 클릭/키보드) ----------
    def _on_detail_button_clicked(self):
        if self._has_detail:
            self.activated.emit()

    def mouseDoubleClickEvent(self, event):  # noqa: N802 - Qt override
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):  # noqa: N802 - Qt override
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if self._has_detail:
                self.activated.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event):  # noqa: N802 - Qt override
        super().focusInEvent(event)
        self._refresh_style()

    def focusOutEvent(self, event):  # noqa: N802 - Qt override
        super().focusOutEvent(event)
        self._refresh_style()

    def _refresh_style(self):
        c = theme.colors()
        focus_border = f"border:{theme.FOCUS_RING_WIDTH}px solid {c['focus']};" if self.hasFocus() else "border:none;"
        self.setStyleSheet(
            f"ForecastRow {{ background-color:transparent; {focus_border}"
            f" border-radius:{theme.RADIUS_CONTROL}px; }}"
            f"ForecastRow:hover {{ background-color:{c['surface_hover']}; }}"
        )
        for page in (self._normal, self._compact):
            for key, color_key in (
                ("date", "text_primary"), ("condition", "text_secondary"),
                ("feels", "text_primary"), ("temp", "text_primary"),
            ):
                page[key].setStyleSheet(f"color:{c[color_key]}; background:transparent; border:none;")
            page["icon"].setPixmap(
                _draw_weather_icon_pixmap(page["condition"].text(), c["text_secondary"], theme.ICON_SIZE_SMALL)
            )
