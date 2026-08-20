"""폭염/풍수해/제설 근무용 날씨 모니터 - CustomTkinter 데스크톱 GUI.

서버 없이 단일 실행 파일(개별 프로그램)로 동작하며, 기상청 API를 직접 호출한다.
"""
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox

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
        else:
            self.favorites.discard(name)
        config.set_favorites(sorted(self.favorites))
        self.on_change()

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
        self.on_saved()
        self.destroy()


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
        self.geometry("1100x680")
        self.minsize(900, 600)
        self.configure(fg_color=COLOR_BG)

        family = _pick_font_family()
        self.font_display = ctk.CTkFont(family=family, size=46, weight="bold")
        self.font_title = ctk.CTkFont(family=family, size=19, weight="bold")
        self.font_subtitle = ctk.CTkFont(family=family, size=14)
        self.font_body = ctk.CTkFont(family=family, size=13)
        self.font_small = ctk.CTkFont(family=family, size=11)

        self.selected_region = None
        self.reports = {}
        self.favorite_buttons = {}

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
        ctk.CTkButton(toolbar, text="즐겨찾기 편집", width=110, command=self._open_region_manager).pack(
            side="right", padx=4
        )
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

        self._build_main_placeholder()

    def _build_main_placeholder(self):
        for widget in self.main_frame.winfo_children():
            widget.destroy()

        header = ctk.CTkFrame(self.main_frame, fg_color=COLOR_CARD, corner_radius=16)
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
            self.main_frame, text="향후 예보 (가져올 수 있는 최대 기간)", font=self.font_body, text_color=COLOR_SUBTEXT,
            anchor="w",
        ).pack(fill="x", pady=(0, 6))

        self.forecast_frame = ctk.CTkScrollableFrame(self.main_frame, fg_color=COLOR_CARD, corner_radius=16)
        self.forecast_frame.pack(fill="both", expand=True)

    # ---------- data ----------
    def _open_region_manager(self):
        RegionManagerDialog(self, self._reload_favorites_and_refresh)

    def _open_settings(self):
        SettingsDialog(self, self.refresh_all)

    def _reload_favorites_and_refresh(self):
        self.refresh_all()

    def refresh_all(self):
        service_key = config.get_service_key()
        if not service_key:
            self.status_label.configure(text="서비스키 미설정 - '설정'에서 입력하세요")
            self._render_favorite_buttons([])
            return

        favorites = config.get_favorites()
        self.status_label.configure(text="조회 중...")
        self._render_favorite_buttons(favorites, loading=True)

        threading.Thread(target=self._fetch_all, args=(service_key, favorites), daemon=True).start()

    def _fetch_all(self, service_key, favorites):
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

        self.reports = reports
        self.after(0, self._on_data_ready, favorites)

    def _on_data_ready(self, favorites):
        self.status_label.configure(text="갱신 완료")
        self._render_favorite_buttons(favorites)
        if favorites and (self.selected_region not in self.reports):
            self.selected_region = favorites[0]
        if self.selected_region:
            self._render_region(self.selected_region)

    # ---------- rendering ----------
    def _render_favorite_buttons(self, favorites, loading=False):
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
            btn = ctk.CTkButton(
                self.favorites_frame,
                text=("조회 중…  " + name) if loading else name,
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
        favorites = config.get_favorites()
        self._render_favorite_buttons(favorites)
        self._render_region(name)

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

        self._render_forecast(report.get("forecast", []))

    def _render_forecast(self, days):
        for widget in self.forecast_frame.winfo_children():
            widget.destroy()

        if not days:
            ctk.CTkLabel(
                self.forecast_frame, text="예보 데이터가 없습니다.", font=self.font_body, text_color=COLOR_SUBTEXT
            ).pack(pady=20)
            return

        for day in days:
            row = ctk.CTkFrame(self.forecast_frame, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=8)

            date_str = day.get("date") or ""
            pretty_date = f"{date_str[4:6]}/{date_str[6:8]}" if len(date_str) == 8 else date_str

            ctk.CTkLabel(row, text=pretty_date, font=self.font_body, text_color=COLOR_TEXT, width=60, anchor="w").pack(
                side="left"
            )
            ctk.CTkLabel(
                row, text=day.get("condition") or "-", font=self.font_body, text_color=COLOR_SUBTEXT, width=160,
                anchor="w",
            ).pack(side="left")
            pop = day.get("pop")
            ctk.CTkLabel(
                row, text=(f"강수 {pop}%" if pop is not None else ""), font=self.font_small,
                text_color=COLOR_ACCENT, width=80, anchor="w",
            ).pack(side="left")
            tmin, tmax = day.get("tmin"), day.get("tmax")
            temp_text = f"{tmin}° / {tmax}°" if (tmin or tmax) else "-"
            ctk.CTkLabel(row, text=temp_text, font=self.font_body, text_color=COLOR_TEXT, width=110, anchor="e").pack(
                side="right"
            )
            ctk.CTkLabel(
                row, text=day.get("source") or "", font=self.font_small, text_color=COLOR_SUBTEXT, width=70,
                anchor="e",
            ).pack(side="right", padx=(0, 8))

            ctk.CTkFrame(self.forecast_frame, fg_color=COLOR_BORDER, height=1).pack(fill="x", padx=16)


def main():
    app = WeatherDutyApp()
    app.mainloop()
