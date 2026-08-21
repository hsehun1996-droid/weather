"""폭염/풍수해/제설 근무용 날씨 모니터 - CustomTkinter 데스크톱 GUI.

서버 없이 단일 실행 파일(개별 프로그램)로 동작하며, 기상청 API를 직접 호출한다.
"""
import re
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, simpledialog

import customtkinter as ctk

from . import config, kma_client, regions

# ---- Apple 시스템 색상에 가깝게 맞춘 팔레트 (light, dark) ----
COLOR_BG = ("#F2F2F7", "#1C1C1E")
COLOR_CARD = ("#FFFFFF", "#2C2C2E")
COLOR_CARD_HOVER = ("#E9E9EE", "#3A3A3C")
COLOR_TEXT = ("#1C1C1E", "#F5F5F7")
COLOR_SUBTEXT = ("#6E6E73", "#98989D")
COLOR_ACCENT = ("#007AFF", "#0A84FF")
COLOR_WARN_BG = ("#FFEBEA", "#3A1F1E")
COLOR_WARN_TEXT = ("#FF3B30", "#FF453A")
COLOR_OK_BG = ("#EAF7ED", "#1F3324")
COLOR_OK_TEXT = ("#34A853", "#30D158")
COLOR_BORDER = ("#D1D1D6", "#3A3A3C")
COLOR_RISK_HIGH = ("#D70015", "#FF453A")
COLOR_RISK_MID = ("#C77700", "#FF9F0A")

_FONT_CANDIDATES = (
    "SF Pro Display",
    "SF Pro Text",
    "Segoe UI Variable",
    "Segoe UI",
    "Helvetica Neue",
    "Apple SD Gothic Neo",
    "Malgun Gothic",
)


def _pick_font_family():
    available = set(tkfont.families())
    for candidate in _FONT_CANDIDATES:
        if candidate in available:
            return candidate
    return "TkDefaultFont"


def _pop_color(pop):
    if pop is None:
        return COLOR_SUBTEXT
    if pop >= 70:
        return COLOR_RISK_HIGH
    if pop >= 50:
        return COLOR_RISK_MID
    return COLOR_ACCENT


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


def _bring_to_front(win):
    """CTkToplevel이 메인 창 뒤에 숨어서 열리는 경우가 있어, 항상 앞으로 띄운다."""
    win.lift()
    win.attributes("-topmost", True)
    win.focus_force()


class HourlyDetailDialog(ctk.CTkToplevel):
    """일자별 예보 칸(지역별 상세/종합보기 어느 쪽이든)을 더블클릭하면 그 날의
    3시간 구간별 날씨/기온/체감온도/강수량/강수확률을 가로로 늘어놓은 표로 보여준다."""

    def __init__(self, master, region_name, day):
        super().__init__(master)
        pretty_date = day.get("date", "")
        if len(pretty_date) == 8:
            pretty_date = f"{pretty_date[:4]}-{pretty_date[4:6]}-{pretty_date[6:8]}"
        self.title(f"{region_name} {pretty_date} 시간별 예보")
        self.configure(fg_color=COLOR_BG)

        font_title = getattr(master, "font_title", None)
        font_body = getattr(master, "font_body", None)
        font_small = getattr(master, "font_small", None)

        ctk.CTkLabel(
            self, text=f"{region_name}  ·  {pretty_date} 시간별 예보", font=font_title, text_color=COLOR_TEXT,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(16, 8))

        hourly = day.get("hourly") or []
        if day.get("source") == "중기예보" or not hourly:
            card = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=12)
            card.pack(fill="both", expand=True, padx=16, pady=(0, 8))
            reason = (
                "중기예보(4일 이후)는 기상청이 강수확률만 제공하고,\n3시간 단위 시간별 데이터는 제공하지 않습니다."
                if day.get("source") == "중기예보"
                else "시간별 데이터가 없습니다."
            )
            ctk.CTkLabel(
                card, text=reason, font=font_small, text_color=COLOR_SUBTEXT, justify="left",
            ).pack(padx=20, pady=40)
            self.geometry("380x220")
        else:
            row_defs = [("날씨", "condition"), ("기온", "temp"), ("체감온도", "feels_like"), ("강수량", "pcp"), ("강수확률", "pop")]
            label_col_w = 90
            hour_col_w = 76

            table = ctk.CTkScrollableFrame(
                self, orientation="horizontal", fg_color=COLOR_CARD, corner_radius=12, height=230
            )
            table.pack(fill="both", expand=True, padx=16, pady=(0, 8))

            ctk.CTkLabel(table, text="시각", font=font_body, text_color=COLOR_SUBTEXT, width=label_col_w, anchor="w").grid(
                row=0, column=0, padx=(12, 8), pady=8, sticky="w"
            )
            for row_idx, (label, _key) in enumerate(row_defs, start=1):
                ctk.CTkLabel(
                    table, text=label, font=font_body, text_color=COLOR_SUBTEXT, width=label_col_w, anchor="w"
                ).grid(row=row_idx, column=0, padx=(12, 8), pady=8, sticky="w")

            for col, hour in enumerate(hourly, start=1):
                ctk.CTkLabel(
                    table, text=_format_fcst_time(hour.get("time")), font=font_body, text_color=COLOR_TEXT,
                    width=hour_col_w,
                ).grid(row=0, column=col, padx=4, pady=8)

                condition_text = hour.get("condition") or "-"
                ctk.CTkLabel(
                    table, text=condition_text, font=font_small, text_color=COLOR_SUBTEXT, width=hour_col_w,
                ).grid(row=1, column=col, padx=4, pady=8)

                temp = hour.get("temp")
                ctk.CTkLabel(
                    table, text=(f"{temp}°" if temp is not None else "-"), font=font_body, text_color=COLOR_TEXT,
                    width=hour_col_w,
                ).grid(row=2, column=col, padx=4, pady=8)

                feels_like = hour.get("feels_like")
                ctk.CTkLabel(
                    table, text=(f"{feels_like:.1f}°" if feels_like is not None else "-"), font=font_body,
                    text_color=COLOR_ACCENT, width=hour_col_w,
                ).grid(row=3, column=col, padx=4, pady=8)

                pcp_val = hour.get("pcp") or "-"
                ctk.CTkLabel(
                    table, text=pcp_val, font=font_small, text_color=COLOR_SUBTEXT, width=hour_col_w,
                ).grid(row=4, column=col, padx=4, pady=8)

                pop_val = hour.get("pop")
                ctk.CTkLabel(
                    table, text=(f"{pop_val}%" if pop_val is not None else "-"), font=font_small,
                    text_color=_pop_color(pop_val), width=hour_col_w,
                ).grid(row=5, column=col, padx=4, pady=8)

            summary_bits = [f"00~24시 누적 강수량: {day.get('pcp') or '강수없음'}"]
            if day.get("tmin") is not None or day.get("tmax") is not None:
                summary_bits.append(f"기온 {day.get('tmin', '-')}° / {day.get('tmax', '-')}°")
            if day.get("feels_like_min") is not None:
                summary_bits.append(f"체감 {day['feels_like_min']}° / {day['feels_like_max']}°")

            summary_card = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=10)
            summary_card.pack(fill="x", padx=16, pady=(0, 8))
            ctk.CTkLabel(
                summary_card, text="   |   ".join(summary_bits), font=font_body, text_color=COLOR_TEXT,
            ).pack(padx=12, pady=10)

            self.geometry("760x420")

        ctk.CTkButton(self, text="닫기", fg_color="transparent", border_width=1, command=self.destroy).pack(
            pady=(0, 16)
        )

        _bring_to_front(self)


class RegionManagerDialog(ctk.CTkToplevel):
    def __init__(self, master, on_change):
        super().__init__(master)
        self.title("즐겨찾기 편집")
        self.geometry("480x560")
        self.on_change = on_change
        self.favorites = set(config.get_favorites())
        self.font_body = master.font_body
        self.font_small = master.font_small

        ctk.CTkLabel(
            self,
            text="지역을 검색해 즐겨찾기에 추가/삭제하세요.",
            font=self.font_body,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(16, 4))

        self.search_var = tk.StringVar()
        search_entry = ctk.CTkEntry(
            self, textvariable=self.search_var, placeholder_text="예: 수원, 강남구, 안동시"
        )
        search_entry.pack(fill="x", padx=16, pady=(0, 8))
        self.search_var.trace_add("write", lambda *_: self._render_results())

        self.results_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.results_frame.pack(fill="both", expand=True, padx=16, pady=8)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 16))
        ctk.CTkButton(
            btn_row, text="+ 위도/경도로 직접 추가", command=self._open_custom_region_form
        ).pack(side="left")
        ctk.CTkButton(btn_row, text="닫기", fg_color="transparent", border_width=1, command=self.destroy).pack(
            side="right"
        )

        self.check_vars = {}
        self._render_results()
        _bring_to_front(self)

    def _current_matches(self):
        query = self.search_var.get().strip()
        all_regions = regions.all_regions()
        if not query:
            names = sorted(self.favorites)
        else:
            names = [n for n in all_regions if query in n]
            names.sort()
        return names[:80]

    def _render_results(self):
        for widget in self.results_frame.winfo_children():
            widget.destroy()
        self.check_vars = {}

        query = self.search_var.get().strip()
        names = self._current_matches()
        if not query and not names:
            ctk.CTkLabel(
                self.results_frame,
                text="아직 즐겨찾기가 없습니다. 위 검색창에 지역명을 입력하세요.",
                font=self.font_small,
                text_color=COLOR_SUBTEXT,
            ).pack(anchor="w", pady=8)
            return
        if query and not names:
            ctk.CTkLabel(
                self.results_frame, text="검색 결과가 없습니다.", font=self.font_small, text_color=COLOR_SUBTEXT
            ).pack(anchor="w", pady=8)
            return

        custom_names = set(regions.load_custom_regions().keys())
        for name in names:
            var = tk.BooleanVar(value=name in self.favorites)
            self.check_vars[name] = var
            label = name + ("  [직접 추가]" if name in custom_names else "")
            ctk.CTkCheckBox(
                self.results_frame,
                text=label,
                variable=var,
                font=self.font_body,
                command=lambda n=name, v=var: self._toggle(n, v),
            ).pack(anchor="w", pady=3, fill="x")

    def _toggle(self, name, var):
        if var.get():
            self.favorites.add(name)
            config.set_favorites(sorted(self.favorites))
            self.on_change(added=name)
        else:
            self.favorites.discard(name)
            config.set_favorites(sorted(self.favorites))
            self.on_change(removed=name)

    def _open_custom_region_form(self):
        CustomRegionForm(self, self._render_results)


class CustomRegionForm(ctk.CTkToplevel):
    def __init__(self, master, on_saved):
        super().__init__(master)
        self.title("지역 직접 추가")
        self.geometry("380x420")
        self.on_saved = on_saved

        fields = [
            ("name", "지역 이름 (예: 우리동네)"),
            ("lat", "위도 (예: 37.5665)"),
            ("lon", "경도 (예: 126.9780)"),
        ]
        self.vars = {}
        for key, placeholder in fields:
            ctk.CTkLabel(self, text=placeholder, anchor="w").pack(fill="x", padx=16, pady=(12, 2))
            var = tk.StringVar()
            ctk.CTkEntry(self, textvariable=var).pack(fill="x", padx=16)
            self.vars[key] = var

        ctk.CTkLabel(self, text="시도 (중기예보 권역 판별용)", anchor="w").pack(fill="x", padx=16, pady=(12, 2))
        self.sido_var = tk.StringVar(value=regions.SIDO_NAMES[0])
        ctk.CTkOptionMenu(self, values=regions.SIDO_NAMES, variable=self.sido_var).pack(fill="x", padx=16)

        ctk.CTkLabel(
            self,
            text="위도/경도는 구글맵 등 지도에서 원하는 위치를 우클릭하면 확인할 수 있습니다.",
            wraplength=340,
            justify="left",
            text_color=COLOR_SUBTEXT,
            font=("", 11),
        ).pack(fill="x", padx=16, pady=(12, 0))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=16, side="bottom")
        ctk.CTkButton(btn_row, text="추가", command=self._save).pack(side="right")
        ctk.CTkButton(btn_row, text="취소", fg_color="transparent", border_width=1, command=self.destroy).pack(
            side="right", padx=8
        )

        _bring_to_front(self)

    def _save(self):
        name = self.vars["name"].get().strip()
        try:
            lat = float(self.vars["lat"].get().strip())
            lon = float(self.vars["lon"].get().strip())
        except ValueError:
            messagebox.showwarning("입력 오류", "위도/경도는 숫자로 입력하세요.", parent=self)
            return
        if not name:
            messagebox.showwarning("입력 필요", "지역 이름을 입력하세요.", parent=self)
            return
        regions.add_custom_region(name, lat, lon, self.sido_var.get())
        config.add_favorite(name)
        self.master.favorites.add(name)
        self.on_saved()
        self.master.on_change(added=name)
        self.destroy()


class BranchManagerDialog(ctk.CTkToplevel):
    """지사(관할 구역) 관리: 지사별로 어떤 즐겨찾기 지역이 속하는지 편집.
    '즐겨찾기 종합 보기'에서 지사 단위로 묶어서 보여주는 데 쓰인다."""

    def __init__(self, master, on_change):
        super().__init__(master)
        self.title("지사 관리")
        self.geometry("460x600")
        self.on_change = on_change
        self.font_body = master.font_body
        self.font_small = master.font_small

        ctk.CTkLabel(
            self,
            text="지사별로 즐겨찾기 지역을 묶어서 관리합니다. 지역 하나가 여러 지사에\n"
            "동시에 속할 수도 있습니다.",
            font=self.font_small,
            text_color=COLOR_SUBTEXT,
            justify="left",
            anchor="w",
        ).pack(fill="x", padx=16, pady=(16, 8))

        self.list_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list_frame.pack(fill="both", expand=True, padx=16, pady=8)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 16))
        ctk.CTkButton(btn_row, text="+ 새 지사 추가", command=self._add_branch).pack(side="left")
        ctk.CTkButton(btn_row, text="닫기", fg_color="transparent", border_width=1, command=self.destroy).pack(
            side="right"
        )

        self._render()
        _bring_to_front(self)

    def _render(self):
        for widget in self.list_frame.winfo_children():
            widget.destroy()

        branches = config.get_branches()
        if not branches:
            ctk.CTkLabel(
                self.list_frame, text="아직 지사가 없습니다. '+ 새 지사 추가'로 만드세요.",
                font=self.font_small, text_color=COLOR_SUBTEXT,
            ).pack(anchor="w", pady=8)
            return

        favorites = config.get_favorites()
        for branch_name in sorted(branches):
            section = ctk.CTkFrame(self.list_frame, fg_color=COLOR_CARD, corner_radius=12)
            section.pack(fill="x", pady=6)

            header = ctk.CTkFrame(section, fg_color="transparent")
            header.pack(fill="x", padx=12, pady=(10, 4))
            ctk.CTkLabel(header, text=branch_name, font=self.font_body, text_color=COLOR_TEXT, anchor="w").pack(
                side="left"
            )
            ctk.CTkButton(
                header, text="지사 삭제", width=70, fg_color="transparent", border_width=1,
                text_color=COLOR_WARN_TEXT, command=lambda b=branch_name: self._remove_branch(b),
            ).pack(side="right")

            for region_name in branches[branch_name]:
                row = ctk.CTkFrame(section, fg_color="transparent")
                row.pack(fill="x", padx=12, pady=2)
                ctk.CTkLabel(
                    row, text=region_name, font=self.font_small, text_color=COLOR_SUBTEXT, anchor="w"
                ).pack(side="left", fill="x", expand=True)
                ctk.CTkButton(
                    row, text="제거", width=50, fg_color="transparent", border_width=1,
                    command=lambda b=branch_name, r=region_name: self._remove_region(b, r),
                ).pack(side="right")

            add_row = ctk.CTkFrame(section, fg_color="transparent")
            add_row.pack(fill="x", padx=12, pady=(4, 10))
            search_var = tk.StringVar()
            entry = ctk.CTkEntry(
                add_row, textvariable=search_var, placeholder_text="즐겨찾기 지역 검색해서 추가"
            )
            entry.pack(side="left", fill="x", expand=True)
            ctk.CTkButton(
                add_row, text="추가", width=60,
                command=lambda b=branch_name, v=search_var: self._add_region_from_search(b, v),
            ).pack(side="left", padx=(6, 0))

    def _add_region_from_search(self, branch_name, search_var):
        query = search_var.get().strip()
        if not query:
            return
        favorites = config.get_favorites()
        matches = [n for n in favorites if query in n]
        if not matches:
            messagebox.showinfo("검색 결과 없음", "일치하는 즐겨찾기 지역이 없습니다. 먼저 즐겨찾기에 추가하세요.", parent=self)
            return
        if len(matches) > 1:
            messagebox.showinfo(
                "여러 개 일치",
                "검색어와 일치하는 지역이 여러 개입니다:\n" + "\n".join(matches[:10]) + "\n더 구체적으로 입력하세요.",
                parent=self,
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
        name = simpledialog.askstring("새 지사 추가", "지사 이름:", parent=self)
        if not name:
            return
        config.add_branch(name.strip())
        self._render()
        self.on_change()


class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, master, on_change):
        super().__init__(master)
        self.title("설정 - 기상청 서비스키")
        self.geometry("520x200")
        self.on_change = on_change

        ctk.CTkLabel(
            self,
            text="공공데이터포털(data.go.kr)에서 발급받은 서비스키(디코딩 키)를 입력하세요.",
            wraplength=470,
            justify="left",
        ).pack(padx=16, pady=(16, 8), anchor="w")

        self.key_var = tk.StringVar(value=config.get_service_key())
        self.entry = ctk.CTkEntry(self, textvariable=self.key_var, width=460, show="*")
        self.entry.pack(padx=16, fill="x")

        self.show_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(self, text="키 표시", variable=self.show_var, command=self._toggle_show).pack(
            anchor="w", padx=16, pady=8
        )

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=12, side="bottom")
        ctk.CTkButton(btn_row, text="저장", command=self._save).pack(side="right")
        ctk.CTkButton(btn_row, text="취소", fg_color="transparent", border_width=1, command=self.destroy).pack(
            side="right", padx=8
        )

        _bring_to_front(self)

    def _toggle_show(self):
        self.entry.configure(show="" if self.show_var.get() else "*")

    def _save(self):
        config.set_service_key(self.key_var.get().strip())
        self.on_change()
        self.destroy()


class WeatherDutyApp(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")
        super().__init__()

        self.title("폭염·풍수해·제설 근무 날씨 모니터")
        self.geometry("1180x700")
        self.minsize(960, 600)
        self.configure(fg_color=COLOR_BG)

        family = _pick_font_family()
        self.font_display = ctk.CTkFont(family=family, size=46, weight="bold")
        self.font_title = ctk.CTkFont(family=family, size=19, weight="bold")
        self.font_subtitle = ctk.CTkFont(family=family, size=14)
        self.font_body = ctk.CTkFont(family=family, size=13)
        self.font_small = ctk.CTkFont(family=family, size=11)

        config.seed_default_branches_if_needed()

        self.selected_region = None
        self.reports = {}
        self.favorite_buttons = {}
        self.view_mode = "detail"
        self.selected_summary_date = None
        self._label_to_date = {}
        self._fetch_seq = 0

        self._build_toolbar()
        self._build_layout()
        self.after(200, self.refresh_all)

    # ---------- layout ----------
    def _build_toolbar(self):
        toolbar = ctk.CTkFrame(self, fg_color="transparent", height=56)
        toolbar.pack(fill="x", padx=16, pady=(14, 6))

        ctk.CTkLabel(
            toolbar, text="폭염·풍수해·제설 근무 날씨 모니터", font=self.font_title, text_color=COLOR_TEXT
        ).pack(side="left")

        self.status_label = ctk.CTkLabel(toolbar, text="", font=self.font_small, text_color=COLOR_SUBTEXT)
        self.status_label.pack(side="right", padx=(12, 0))

        ctk.CTkButton(toolbar, text="설정", width=84, command=self._open_settings).pack(side="right", padx=4)
        ctk.CTkButton(toolbar, text="지사 관리", width=90, command=self._open_branch_manager).pack(
            side="right", padx=4
        )
        ctk.CTkButton(toolbar, text="즐겨찾기 편집", width=110, command=self._open_region_manager).pack(
            side="right", padx=4
        )
        self.view_toggle_btn = ctk.CTkButton(
            toolbar, text="즐겨찾기 종합 보기", width=140, command=self._toggle_view_mode
        )
        self.view_toggle_btn.pack(side="right", padx=4)
        ctk.CTkButton(toolbar, text="새로고침", width=84, command=self.refresh_all).pack(side="right", padx=4)

    def _build_layout(self):
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        sidebar = ctk.CTkFrame(body, width=250, fg_color=COLOR_CARD, corner_radius=16)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        ctk.CTkLabel(
            sidebar, text="즐겨찾기 지역", font=self.font_body, text_color=COLOR_SUBTEXT, anchor="w"
        ).pack(fill="x", padx=16, pady=(16, 8))

        self.favorites_frame = ctk.CTkScrollableFrame(sidebar, fg_color="transparent")
        self.favorites_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.main_frame = ctk.CTkFrame(body, fg_color="transparent")
        self.main_frame.pack(side="left", fill="both", expand=True, padx=(16, 0))

        self.detail_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.summary_container = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.summary_date_bar = ctk.CTkFrame(self.summary_container, fg_color=COLOR_CARD, corner_radius=16)
        self.summary_date_bar.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(
            self.summary_date_bar, text="날짜 선택", font=self.font_body, text_color=COLOR_SUBTEXT,
        ).pack(side="left", padx=(16, 8), pady=12)
        self.summary_date_selector = ctk.CTkSegmentedButton(
            self.summary_date_bar, command=self._on_summary_date_selected
        )
        self.summary_date_selector.pack(side="left", padx=(0, 16), pady=12, fill="x", expand=True)
        self.summary_frame = ctk.CTkScrollableFrame(
            self.summary_container, fg_color=COLOR_CARD, corner_radius=16
        )
        self.summary_frame.pack(fill="both", expand=True)

        self._build_detail_widgets(self.detail_frame)
        self.detail_frame.pack(fill="both", expand=True)

    def _build_detail_widgets(self, parent):
        header = ctk.CTkFrame(parent, fg_color=COLOR_CARD, corner_radius=16)
        header.pack(fill="x", pady=(0, 12))

        top_row = ctk.CTkFrame(header, fg_color="transparent")
        top_row.pack(fill="x", padx=20, pady=(18, 0))
        self.region_name_label = ctk.CTkLabel(
            top_row, text="즐겨찾기 지역을 선택하세요", font=self.font_title, text_color=COLOR_TEXT, anchor="w"
        )
        self.region_name_label.pack(side="left")
        self.obs_time_label = ctk.CTkLabel(top_row, text="", font=self.font_small, text_color=COLOR_SUBTEXT)
        self.obs_time_label.pack(side="right")

        current_row = ctk.CTkFrame(header, fg_color="transparent")
        current_row.pack(fill="x", padx=20, pady=(4, 4))
        self.temp_label = ctk.CTkLabel(current_row, text="-℃", font=self.font_display, text_color=COLOR_TEXT)
        self.temp_label.pack(side="left")

        detail_col = ctk.CTkFrame(current_row, fg_color="transparent")
        detail_col.pack(side="left", padx=(16, 0), pady=(10, 0))
        self.rain_label = ctk.CTkLabel(
            detail_col, text="1시간 강수량 -mm", font=self.font_body, text_color=COLOR_SUBTEXT, anchor="w"
        )
        self.rain_label.pack(anchor="w")
        self.error_label = ctk.CTkLabel(
            detail_col, text="", font=self.font_small, text_color=COLOR_WARN_TEXT, anchor="w", justify="left",
            wraplength=650,
        )
        self.error_label.pack(anchor="w", pady=(4, 0))

        self.warning_banner = ctk.CTkLabel(
            header,
            text="현재 발효 중인 특보 없음",
            font=self.font_body,
            fg_color=COLOR_OK_BG,
            text_color=COLOR_OK_TEXT,
            corner_radius=10,
            anchor="w",
            justify="left",
            wraplength=1000,
        )
        self.warning_banner.pack(fill="x", padx=20, pady=(8, 18), ipady=8)

        ctk.CTkLabel(
            parent, text="향후 예보 (가져올 수 있는 최대 기간)", font=self.font_body, text_color=COLOR_SUBTEXT,
            anchor="w",
        ).pack(fill="x", pady=(0, 6))

        self.forecast_frame = ctk.CTkScrollableFrame(parent, fg_color=COLOR_CARD, corner_radius=16)
        self.forecast_frame.pack(fill="both", expand=True)

    # ---------- view mode ----------
    def _toggle_view_mode(self):
        if self.view_mode == "detail":
            self.view_mode = "summary"
            self.detail_frame.pack_forget()
            self.summary_container.pack(fill="both", expand=True)
            self.view_toggle_btn.configure(text="지역별 상세 보기")
        else:
            self.view_mode = "detail"
            self.summary_container.pack_forget()
            self.detail_frame.pack(fill="both", expand=True)
            self.view_toggle_btn.configure(text="즐겨찾기 종합 보기")
        self._refresh_current_view()

    def _on_summary_date_selected(self, date_label):
        self.selected_summary_date = self._label_to_date.get(date_label)
        self._render_summary(config.get_favorites())

    def _refresh_current_view(self):
        favorites = config.get_favorites()
        self._render_favorite_buttons(favorites)
        if self.view_mode == "summary":
            self._render_summary(favorites)
        elif self.selected_region:
            self._render_region(self.selected_region)

    # ---------- dialogs ----------
    def _open_region_manager(self):
        RegionManagerDialog(self, self._on_favorite_changed)

    def _open_branch_manager(self):
        BranchManagerDialog(self, self._refresh_current_view)

    def _open_settings(self):
        SettingsDialog(self, self.refresh_all)

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
            self.status_label.configure(text="서비스키 미설정 - '설정'에서 입력하세요")
            self.reports = {}
            self._refresh_current_view()
            return

        favorites = config.get_favorites()
        self.status_label.configure(text="조회 중...")
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

        self.after(0, self._apply_fetch_result, seq, reports, favorites)

    def _apply_fetch_result(self, seq, reports, favorites):
        if seq != self._fetch_seq:
            return  # 새 새로고침이 이미 시작돼 이 결과는 낡은 것 -> 버린다
        self.status_label.configure(text="갱신 완료")
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
        self.after(0, self._merge_one_report, name, report)

    def _merge_one_report(self, name, report):
        self.reports[name] = report
        self._refresh_current_view()

    # ---------- rendering: sidebar ----------
    def _render_favorite_buttons(self, favorites):
        for widget in self.favorites_frame.winfo_children():
            widget.destroy()
        self.favorite_buttons = {}

        if not favorites:
            ctk.CTkLabel(
                self.favorites_frame,
                text="즐겨찾기가 비어 있습니다.\n'즐겨찾기 편집'에서 추가하세요.",
                font=self.font_small,
                text_color=COLOR_SUBTEXT,
                justify="left",
            ).pack(anchor="w", padx=8, pady=8)
            return

        for name in favorites:
            is_selected = name == self.selected_region
            is_loading = name not in self.reports
            btn = ctk.CTkButton(
                self.favorites_frame,
                text=("조회 중…  " + name) if is_loading else name,
                anchor="w",
                fg_color=COLOR_ACCENT if is_selected else "transparent",
                text_color=("#FFFFFF" if is_selected else COLOR_TEXT[0], "#FFFFFF" if is_selected else COLOR_TEXT[1]),
                hover_color=COLOR_CARD_HOVER,
                font=self.font_body,
                corner_radius=10,
                command=lambda n=name: self._select_region(n),
            )
            btn.pack(fill="x", padx=8, pady=3)
            self.favorite_buttons[name] = btn

    def _select_region(self, name):
        self.selected_region = name
        if self.view_mode != "detail":
            self.view_mode = "detail"
            self.summary_container.pack_forget()
            self.detail_frame.pack(fill="both", expand=True)
            self.view_toggle_btn.configure(text="즐겨찾기 종합 보기")
        self._refresh_current_view()

    # ---------- rendering: detail view ----------
    def _render_region(self, name):
        report = self.reports.get(name)
        if not report:
            self.region_name_label.configure(text=name)
            self.temp_label.configure(text="조회 중…")
            return

        current = report.get("current") or {}
        temp = current.get("temp")
        rain = current.get("rain_1h")
        obs_time = current.get("obs_time", "-")

        self.region_name_label.configure(text=name)
        self.temp_label.configure(text=(f"{temp}℃" if temp is not None else "-℃"))
        self.rain_label.configure(text=f"1시간 강수량 {rain if rain is not None else '-'}mm")
        self.obs_time_label.configure(text=f"관측시각 {obs_time}")

        errors = report.get("errors") or []
        self.error_label.configure(text="\n".join(errors))

        warnings = report.get("warnings") or []
        if warnings:
            self.warning_banner.configure(
                text="⚠ 특보 발효 중: " + " | ".join(warnings),
                fg_color=COLOR_WARN_BG,
                text_color=COLOR_WARN_TEXT,
            )
        else:
            self.warning_banner.configure(
                text="현재 발효 중인 특보 없음  (당일 기준, 향후 예정일은 표시되지 않음)",
                fg_color=COLOR_OK_BG,
                text_color=COLOR_OK_TEXT,
            )

        self._render_forecast(name, report.get("forecast", []))

    def _render_forecast(self, region_name, days):
        for widget in self.forecast_frame.winfo_children():
            widget.destroy()

        if not days:
            ctk.CTkLabel(
                self.forecast_frame, text="예보 데이터가 없습니다.", font=self.font_body, text_color=COLOR_SUBTEXT
            ).pack(pady=20)
            return

        for day in days:
            row = ctk.CTkFrame(self.forecast_frame, fg_color="transparent", cursor="hand2")
            row.pack(fill="x", padx=16, pady=8)
            row_widgets = [row]

            date_str = day.get("date") or ""
            pretty_date = f"{date_str[4:6]}/{date_str[6:8]}" if len(date_str) == 8 else date_str

            row_widgets.append(
                ctk.CTkLabel(row, text=pretty_date, font=self.font_body, text_color=COLOR_TEXT, width=60, anchor="w")
            )
            row_widgets.append(
                ctk.CTkLabel(
                    row, text=day.get("condition") or "-", font=self.font_body, text_color=COLOR_SUBTEXT, width=130,
                    anchor="w",
                )
            )

            pop = day.get("pop")
            pop_text = f"강수확률 {pop}%" if pop is not None else "강수확률 -"
            row_widgets.append(
                ctk.CTkLabel(row, text=pop_text, font=self.font_small, text_color=_pop_color(pop), width=90, anchor="w")
            )

            row_widgets.append(
                ctk.CTkLabel(
                    row, text=f"강수량 {_pcp_display_text(day)}", font=self.font_small, text_color=COLOR_SUBTEXT,
                    width=170, anchor="w",
                )
            )

            tmin, tmax = day.get("tmin"), day.get("tmax")
            temp_text = f"{tmin}° / {tmax}°" if (tmin or tmax) else "-"
            fl_min, fl_max = day.get("feels_like_min"), day.get("feels_like_max")
            feels_text = f"체감 {fl_min}° / {fl_max}°" if fl_min is not None else ""

            for widget in row_widgets[1:]:
                widget.pack(side="left")
            if feels_text:
                row_widgets.append(
                    ctk.CTkLabel(row, text=feels_text, font=self.font_small, text_color=COLOR_ACCENT, anchor="w")
                )
                row_widgets[-1].pack(side="left", padx=(8, 0))

            source_label = ctk.CTkLabel(
                row, text=day.get("source") or "", font=self.font_small, text_color=COLOR_SUBTEXT, width=70,
                anchor="e",
            )
            source_label.pack(side="right", padx=(0, 8))
            row_widgets.append(source_label)

            temp_label = ctk.CTkLabel(row, text=temp_text, font=self.font_body, text_color=COLOR_TEXT, width=110, anchor="e")
            temp_label.pack(side="right")
            row_widgets.append(temp_label)

            for widget in row_widgets:
                widget.bind("<Double-Button-1>", lambda _e, d=day: self._open_hourly_detail(region_name, d))

            ctk.CTkFrame(self.forecast_frame, fg_color=COLOR_BORDER, height=1).pack(fill="x", padx=16)

    def _open_hourly_detail(self, region_name, day):
        HourlyDetailDialog(self, region_name, day)

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
        labels = []
        self._label_to_date = {}
        for date_str in all_dates:
            pretty = f"{date_str[4:6]}/{date_str[6:8]}" if len(date_str) == 8 else date_str
            labels.append(pretty)
            self._label_to_date[pretty] = date_str

        if not labels:
            self.summary_date_selector.configure(values=[])
            return

        self.summary_date_selector.configure(values=labels)
        if self.selected_summary_date not in all_dates:
            self.selected_summary_date = all_dates[0]
        selected_label = next(lbl for lbl, d in self._label_to_date.items() if d == self.selected_summary_date)
        self.summary_date_selector.set(selected_label)

    def _render_summary(self, favorites):
        for widget in self.summary_frame.winfo_children():
            widget.destroy()

        if not favorites:
            ctk.CTkLabel(
                self.summary_frame, text="즐겨찾기가 비어 있습니다.", font=self.font_body, text_color=COLOR_SUBTEXT
            ).grid(row=0, column=0, padx=16, pady=20)
            return

        all_dates = self._all_summary_dates(favorites)
        self._update_summary_date_selector(all_dates)

        if not all_dates:
            ctk.CTkLabel(
                self.summary_frame, text="예보 데이터를 불러오는 중입니다…", font=self.font_body,
                text_color=COLOR_SUBTEXT,
            ).grid(row=0, column=0, padx=16, pady=20)
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

        branch_col_w, name_col_w, temp_col_w, feels_col_w, pop_col_w, pcp_col_w, warn_col_w = (
            100, 180, 90, 100, 80, 120, 55,
        )
        headers = [
            ("지사", branch_col_w, "w"), ("지역", name_col_w, "w"), ("최저/최고", temp_col_w, "center"),
            ("체감 최저/최고", feels_col_w, "center"), ("강수확률", pop_col_w, "center"),
            ("강수량(00~24시 누적)", pcp_col_w, "center"), ("특보", warn_col_w, "center"),
        ]
        for col, (label, width, anchor) in enumerate(headers):
            ctk.CTkLabel(
                self.summary_frame, text=label, font=self.font_body, text_color=COLOR_SUBTEXT, width=width,
                anchor=anchor,
            ).grid(row=0, column=col, padx=(16 if col == 0 else 4, 16 if col == len(headers) - 1 else 4),
                   pady=(16, 8), sticky=("w" if anchor == "w" else ""))

        row_idx = 1
        for branch_name, members in groups:
            start_row = row_idx

            member_days = {}
            best_name, best_amount = None, -1.0
            for region_name in members:
                report = self.reports.get(region_name)
                day = None
                if report:
                    day = next(
                        (d for d in report.get("forecast", []) if d.get("date") == target_date), None
                    )
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

                row_bg = COLOR_WARN_BG if is_best else "transparent"
                emph_color = COLOR_WARN_TEXT if is_best else COLOR_TEXT
                row_cells = []

                name_text = ("조회 중… " + region_name) if is_loading else region_name
                row_cells.append(ctk.CTkLabel(
                    self.summary_frame, text=name_text, font=self.font_body, text_color=emph_color,
                    width=name_col_w, anchor="w", fg_color=row_bg, corner_radius=6, cursor=("hand2" if day else "arrow"),
                ))
                row_cells[-1].grid(row=row_idx, column=1, padx=4, pady=3, sticky="ew", ipady=3)

                tmin, tmax = (day.get("tmin"), day.get("tmax")) if day else (None, None)
                temp_text = f"{tmin}°/{tmax}°" if (tmin is not None or tmax is not None) else "-"
                row_cells.append(ctk.CTkLabel(
                    self.summary_frame, text=temp_text, font=self.font_small, text_color=COLOR_TEXT,
                    width=temp_col_w, fg_color=row_bg, corner_radius=6, cursor=("hand2" if day else "arrow"),
                ))
                row_cells[-1].grid(row=row_idx, column=2, padx=4, pady=3, ipady=3)

                fl_min, fl_max = (day.get("feels_like_min"), day.get("feels_like_max")) if day else (None, None)
                if fl_min is not None:
                    feels_text = f"{fl_min}°/{fl_max}°"
                elif day and day.get("source") == "중기예보":
                    feels_text = "중기예보만"
                else:
                    feels_text = "-"
                row_cells.append(ctk.CTkLabel(
                    self.summary_frame, text=feels_text, font=self.font_small, text_color=COLOR_ACCENT,
                    width=feels_col_w, fg_color=row_bg, corner_radius=6, cursor=("hand2" if day else "arrow"),
                ))
                row_cells[-1].grid(row=row_idx, column=3, padx=4, pady=3, ipady=3)

                pop = day.get("pop") if day else None
                pop_text = f"{pop}%" if pop is not None else "-"
                row_cells.append(ctk.CTkLabel(
                    self.summary_frame, text=pop_text, font=self.font_small, text_color=_pop_color(pop),
                    width=pop_col_w, fg_color=row_bg, corner_radius=6, cursor=("hand2" if day else "arrow"),
                ))
                row_cells[-1].grid(row=row_idx, column=4, padx=4, pady=3, ipady=3)

                if day is None:
                    pcp_text = "-"
                elif day.get("pcp"):
                    pcp_text = day.get("pcp")
                elif day.get("source") == "중기예보":
                    pcp_text = "중기예보만"
                else:
                    pcp_text = "강수없음"
                row_cells.append(ctk.CTkLabel(
                    self.summary_frame, text=pcp_text,
                    font=ctk.CTkFont(family=self.font_body.cget("family"), size=13, weight=("bold" if is_best else "normal")),
                    text_color=emph_color, width=pcp_col_w, fg_color=row_bg,
                    corner_radius=6, cursor=("hand2" if day else "arrow"),
                ))
                row_cells[-1].grid(row=row_idx, column=5, padx=4, pady=3, ipady=3)

                warn_text = "⚠" if (report and report.get("warnings")) else ""
                row_cells.append(ctk.CTkLabel(
                    self.summary_frame, text=warn_text, font=self.font_small, text_color=COLOR_WARN_TEXT,
                    width=warn_col_w, fg_color=row_bg, corner_radius=6, cursor=("hand2" if day else "arrow"),
                ))
                row_cells[-1].grid(row=row_idx, column=6, padx=(4, 16), pady=3, ipady=3)

                if day:
                    for cell in row_cells:
                        cell.bind(
                            "<Double-Button-1>", lambda _e, n=region_name, d=day: self._open_hourly_detail(n, d)
                        )

                row_idx += 1

            ctk.CTkLabel(
                self.summary_frame, text=branch_name, font=self.font_body, text_color=COLOR_TEXT,
                width=branch_col_w, fg_color=COLOR_BG, corner_radius=8,
            ).grid(row=start_row, column=0, rowspan=(row_idx - start_row), padx=(16, 4), pady=3, sticky="ns", ipady=6)


def main():
    app = WeatherDutyApp()
    app.mainloop()
