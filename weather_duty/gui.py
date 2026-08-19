"""폭염/풍수해/제설 근무용 날씨 모니터 - tkinter 데스크톱 GUI.

서버 없이 단일 실행 파일(개별 프로그램)로 동작하며, 기상청 API를 직접 호출한다.
"""
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from . import config, kma_client, regions


class RegionManagerDialog(tk.Toplevel):
    def __init__(self, master, on_change):
        super().__init__(master)
        self.title("지역 관리 (즐겨찾기 편집)")
        self.geometry("420x420")
        self.on_change = on_change

        self.favorites = set(config.get_favorites())

        tk.Label(self, text="즐겨찾기에 표시할 지역을 선택하세요.", anchor="w").pack(fill="x", padx=10, pady=(10, 0))

        list_frame = tk.Frame(self)
        list_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.canvas = tk.Canvas(list_frame)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.canvas.yview)
        self.checklist_frame = tk.Frame(self.canvas)
        self.checklist_frame.bind(
            "<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.create_window((0, 0), window=self.checklist_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.vars = {}
        self._render_checklist()

        btn_frame = tk.Frame(self)
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))
        tk.Button(btn_frame, text="+ 지역 직접 추가", command=self._add_custom_region).pack(side="left")
        tk.Button(btn_frame, text="선택 지역 삭제(사용자 정의만)", command=self._remove_selected_custom).pack(
            side="left", padx=5
        )
        tk.Button(btn_frame, text="저장", command=self._save).pack(side="right")
        tk.Button(btn_frame, text="닫기", command=self.destroy).pack(side="right", padx=5)

    def _render_checklist(self):
        for widget in self.checklist_frame.winfo_children():
            widget.destroy()
        self.vars = {}
        all_regions = regions.all_regions()
        custom_names = set(regions.load_custom_regions().keys())
        for name in sorted(all_regions):
            var = tk.BooleanVar(value=name in self.favorites)
            self.vars[name] = var
            label = name + ("  [사용자정의]" if name in custom_names else "")
            tk.Checkbutton(self.checklist_frame, text=label, variable=var, anchor="w").pack(fill="x")

    def _add_custom_region(self):
        name = simpledialog.askstring("지역 추가", "지역 이름:", parent=self)
        if not name:
            return
        nx = simpledialog.askinteger("지역 추가", "격자 좌표 nx (단기예보용):", parent=self)
        ny = simpledialog.askinteger("지역 추가", "격자 좌표 ny (단기예보용):", parent=self)
        reg_id = simpledialog.askstring(
            "지역 추가", "중기예보구역코드 regId (선택, 모르면 비워두기):", parent=self
        )
        keyword = simpledialog.askstring(
            "지역 추가", "특보 매칭용 키워드 (선택, 비우면 지역명 사용):", parent=self
        )
        if nx is None or ny is None:
            messagebox.showwarning("입력 필요", "nx, ny 좌표는 필수입니다.")
            return
        regions.add_custom_region(name, nx, ny, reg_id or None, keyword or None)
        self._render_checklist()

    def _remove_selected_custom(self):
        custom_names = set(regions.load_custom_regions().keys())
        to_remove = [name for name, var in self.vars.items() if var.get() and name in custom_names]
        if not to_remove:
            messagebox.showinfo("삭제", "삭제할 사용자 정의 지역을 먼저 체크하세요.")
            return
        for name in to_remove:
            regions.remove_custom_region(name)
            self.favorites.discard(name)
        self._render_checklist()

    def _save(self):
        selected = [name for name, var in self.vars.items() if var.get()]
        config.set_favorites(selected)
        self.on_change()
        self.destroy()


class SettingsDialog(tk.Toplevel):
    def __init__(self, master, on_change):
        super().__init__(master)
        self.title("설정 - 기상청 서비스키")
        self.geometry("480x160")
        self.on_change = on_change

        tk.Label(
            self,
            text="공공데이터포털(data.go.kr)에서 발급받은 서비스키(디코딩 키)를 입력하세요.",
            wraplength=440,
            justify="left",
        ).pack(padx=10, pady=10, anchor="w")

        self.key_var = tk.StringVar(value=config.get_service_key())
        entry = tk.Entry(self, textvariable=self.key_var, width=60, show="*")
        entry.pack(padx=10, fill="x")

        show_var = tk.BooleanVar(value=False)

        def toggle_show():
            entry.config(show="" if show_var.get() else "*")

        tk.Checkbutton(self, text="키 표시", variable=show_var, command=toggle_show).pack(anchor="w", padx=10)

        btn_frame = tk.Frame(self)
        btn_frame.pack(fill="x", padx=10, pady=10)
        tk.Button(btn_frame, text="저장", command=self._save).pack(side="right")
        tk.Button(btn_frame, text="취소", command=self.destroy).pack(side="right", padx=5)

    def _save(self):
        config.set_service_key(self.key_var.get().strip())
        self.on_change()
        self.destroy()


class WeatherDutyApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("폭염·풍수해·제설 근무 날씨 모니터")
        self.geometry("980x600")

        self.selected_region = tk.StringVar()
        self.reports = {}

        self._build_menu()
        self._build_layout()
        self.after(200, self.refresh_all)

    def _build_menu(self):
        toolbar = tk.Frame(self)
        toolbar.pack(fill="x", padx=8, pady=8)
        tk.Button(toolbar, text="새로고침", command=self.refresh_all).pack(side="left")
        tk.Button(toolbar, text="즐겨찾기 편집", command=self._open_region_manager).pack(side="left", padx=5)
        tk.Button(toolbar, text="설정(서비스키)", command=self._open_settings).pack(side="left")
        self.status_label = tk.Label(toolbar, text="", fg="gray")
        self.status_label.pack(side="right")

    def _build_layout(self):
        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=8, pady=8)

        left = tk.Frame(body, width=220)
        left.pack(side="left", fill="y")
        tk.Label(left, text="즐겨찾기 지역", font=("", 11, "bold")).pack(anchor="w")
        self.region_list = tk.Listbox(left, width=25)
        self.region_list.pack(fill="y", expand=True, pady=5)
        self.region_list.bind("<<ListboxSelect>>", self._on_select_region)

        right = tk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(15, 0))

        self.summary_label = tk.Label(right, text="", font=("", 12, "bold"), anchor="w", justify="left")
        self.summary_label.pack(fill="x")

        self.warning_label = tk.Label(right, text="", fg="red", font=("", 11, "bold"), anchor="w")
        self.warning_label.pack(fill="x", pady=(2, 8))

        columns = ("date", "tmin", "tmax", "pop", "pcp", "condition", "source")
        self.tree = ttk.Treeview(right, columns=columns, show="headings", height=12)
        headings = {
            "date": "날짜",
            "tmin": "최저기온(℃)",
            "tmax": "최고기온(℃)",
            "pop": "강수확률(%)",
            "pcp": "강수량",
            "condition": "날씨",
            "source": "출처",
        }
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=110, anchor="center")
        self.tree.pack(fill="both", expand=True)

    def _open_region_manager(self):
        RegionManagerDialog(self, self.refresh_all)

    def _open_settings(self):
        SettingsDialog(self, self.refresh_all)

    def refresh_all(self):
        service_key = config.get_service_key()
        if not service_key:
            self.status_label.config(text="서비스키 미설정 - '설정(서비스키)'에서 입력하세요.")
            return

        favorites = config.get_favorites()
        self.status_label.config(text="조회 중...")
        self.region_list.delete(0, tk.END)
        for name in favorites:
            self.region_list.insert(tk.END, name)

        threading.Thread(target=self._fetch_all, args=(service_key, favorites), daemon=True).start()

    def _fetch_all(self, service_key, favorites):
        all_regions = regions.all_regions()
        try:
            warnings = kma_client.get_active_warnings(service_key)
        except Exception as exc:  # noqa: BLE001
            warnings = []
            self.after(0, lambda: self.status_label.config(text=f"특보 조회 실패: {exc}"))

        reports = {}
        for name in favorites:
            info = all_regions.get(name)
            if not info:
                continue
            reports[name] = kma_client.build_region_report(service_key, name, info, warnings)

        self.reports = reports
        self.after(0, self._on_data_ready)

    def _on_data_ready(self):
        self.status_label.config(text="갱신 완료")
        if self.reports and not self.selected_region.get():
            self.region_list.selection_set(0)
            self._render_region(next(iter(self.reports)))
        elif self.selected_region.get() in self.reports:
            self._render_region(self.selected_region.get())

    def _on_select_region(self, _event):
        selection = self.region_list.curselection()
        if not selection:
            return
        name = self.region_list.get(selection[0])
        self.selected_region.set(name)
        self._render_region(name)

    def _render_region(self, name):
        report = self.reports.get(name)
        if not report:
            return

        current = report.get("current") or {}
        temp = current.get("temp", "-")
        rain = current.get("rain_1h", "-")
        obs_time = current.get("obs_time", "-")
        summary = f"{name}  |  현재기온 {temp}℃  |  1시간 강수량 {rain}mm  |  관측시각 {obs_time}"
        if report.get("errors"):
            summary += "\n" + " / ".join(report["errors"])
        self.summary_label.config(text=summary)

        warnings = report.get("warnings") or []
        if warnings:
            self.warning_label.config(text="⚠ 특보 발효 중: " + " | ".join(warnings))
        else:
            self.warning_label.config(text="현재 발효 중인 특보 없음 (당일 기준, 향후 예정일은 표시되지 않음)")

        for row in self.tree.get_children():
            self.tree.delete(row)
        for day in report.get("forecast", []):
            self.tree.insert(
                "",
                tk.END,
                values=(
                    day.get("date"),
                    day.get("tmin") or "-",
                    day.get("tmax") or "-",
                    day.get("pop") if day.get("pop") is not None else "-",
                    day.get("pcp") or "-",
                    day.get("condition") or "-",
                    day.get("source"),
                ),
            )


def main():
    app = WeatherDutyApp()
    app.mainloop()
