"""사진 날짜별 정리 및 JPG/NEF/MOV 분류의 버튼식 Windows 프로그램."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from photo_organizer.ui.common import configure_window, enable_dpi_awareness, Workspace, file_table, checkbox, set_checked, cancel_callbacks
from photo_organizer.core import jobs as jobs
from photo_organizer.windows.folder_views import ExplorerOptions, VIEW_MODES, SORT_KEYS

PROFILES = {
    "date": ("사진 날짜별 정리", "사진과 동영상을 촬영 날짜별 폴더로 모아요.",
             "NEF는 수정한 날짜를 유지합니다. 나머지 파일은 촬영 날짜에 맞춥니다."),
    "type": ("파일 분류", "JPG · NEF · MOV 파일을 종류별 폴더로 나눠요.",
             "선택한 폴더 바로 안의 파일만 분류합니다. 같은 이름이 있으면 원본을 남겨 둡니다."),
}


class ExplorerDialog:
    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root)
        window = self.window
        window.title("탐색기 보기·정렬")
        window.configure(background="white")
        window.transient(app.root)
        window.resizable(False, False)
        window.protocol("WM_DELETE_WINDOW", self.close)
        px = lambda number: round(number * max(1, window.winfo_fpixels("1i") / 96))
        page = ttk.Frame(window, padding=px(22))
        page.pack(fill="both", expand=True)
        ttk.Label(page, text="탐색기 보기·정렬", style="ModalTitle.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")
        folder_label = "날짜 폴더" if app.mode == "date" else "분류 폴더"
        description = (f"선택한 폴더와 {folder_label}의 보기·정렬을 설정합니다." if app.mode == "date"
                       else "JPG · NEF · MOV 폴더의 보기·정렬을 설정합니다.")
        ttk.Label(page, text=description, style="Subtitle.TLabel").grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(px(8), px(18)))
        for column, text in enumerate(["대상", "보기", "정렬 기준", "순서"]):
            ttk.Label(page, text=text, style="Heading.TLabel").grid(row=2, column=column, sticky="w", padx=(0, px(14)))
        options = app.view_options
        self.values, self.combos = {}, {}
        profiles = ([(3, "general", "일반 폴더", options.general_view, options.general_sort, options.general_ascending)]
                    if app.mode == "date" else [])
        profiles += [
            (4, "date", folder_label, options.date_view, options.date_sort, options.date_ascending),
        ]
        for row, prefix, label, view, sort, ascending in profiles:
            ttk.Label(page, text=label).grid(row=row, column=0, sticky="w", padx=(0, px(16)))
            for column, field, current, choices, width in [
                (1, "view", view, list(VIEW_MODES), 16),
                (2, "sort", sort, (["자동"] if prefix == "date" else []) + list(SORT_KEYS), 16),
                (3, "order", "오름차순" if ascending else "내림차순", ["오름차순", "내림차순"], 10),
            ]:
                name = prefix + "_" + field
                variable = tk.StringVar(window, current)
                self.values[name] = variable
                combo = ttk.Combobox(page, textvariable=variable, values=choices, state="readonly", width=width)
                combo.grid(row=row, column=column, sticky="ew", padx=(0, px(12) if column < 3 else 0), pady=px(10))
                self.combos[name] = combo
        self.auto_apply = tk.BooleanVar(window, options.auto_apply)
        ttk.Checkbutton(page, text="정리 후에도 이 설정 적용", variable=self.auto_apply).grid(
            row=5, column=0, columnspan=4, sticky="w", pady=(px(10), px(9)))
        ttk.Label(page, text="자동 정렬: NEF·영상은 수정한 날짜, 일반 사진은 찍은 날짜를 사용합니다.",
            style="Muted.TLabel").grid(row=6, column=0, columnspan=4, sticky="w")
        ttk.Label(page, text="이미 열린 탐색기는 닫았다가 다시 열어 주세요.", style="Muted.TLabel").grid(
            row=7, column=0, columnspan=4, sticky="w", pady=(px(6), px(18)))
        buttons = ttk.Frame(page)
        buttons.grid(row=8, column=0, columnspan=4, sticky="e")
        self.cancel_button = ttk.Button(buttons, text="취소", command=self.close)
        self.cancel_button.pack(side="left", padx=(0, px(10)))
        self.apply_button = ttk.Button(buttons, text="적용", style="Primary.TButton", command=self.apply)
        self.apply_button.pack(side="left")
        window.bind("<Escape>", lambda event: self.close())
        window.update_idletasks()
        left = app.root.winfo_rootx() + (app.root.winfo_width() - window.winfo_reqwidth()) // 2
        top = app.root.winfo_rooty() + (app.root.winfo_height() - window.winfo_reqheight()) // 2
        window.geometry(f"+{max(0, left)}+{max(0, top)}")
        window.grab_set()

    def apply(self):
        values = {key: value.get() for key, value in self.values.items()}
        options = ExplorerOptions(
            general_view=values.get("general_view", self.app.view_options.general_view),
            general_sort=values.get("general_sort", self.app.view_options.general_sort),
            general_ascending=(values["general_order"] == "오름차순" if "general_order" in values
                               else self.app.view_options.general_ascending),
            date_view=values["date_view"], date_sort=values["date_sort"],
            date_ascending=values["date_order"] == "오름차순", auto_apply=self.auto_apply.get())
        self.close()
        self.app.apply_view_settings(options)

    def close(self):
        self.window.grab_release()
        self.window.destroy()
        self.app.view_dialog = None


class OrganizerApp:
    def __init__(self, root, mode="date", initial_folder=None):
        self.root, self.mode = root, mode
        self.title, self.subtitle, self.detail = PROFILES[mode]
        self.folder = tk.StringVar(root)
        self.recursive = tk.BooleanVar(root, True)
        self.heading = tk.StringVar(root, "폴더를 선택해 주세요")
        self.status = tk.StringVar(root, "이동할 위치를 먼저 확인한 뒤 실행할 수 있어요.")
        self.selection_text = tk.StringVar(root)
        self.plan = None
        self.view_options = getattr(root, "_photo_view_options", ExplorerOptions())
        self.view_dialog = None
        self.checked = set()
        self.busy = False
        self.operation = ""
        self.finished = False
        self.closed = False
        self.events = queue.Queue()
        self._build()
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = root.after(80, self._poll)
        self.initial_scan_id = None
        if initial_folder:
            self.folder.set(str(initial_folder))
            self.initial_scan_id = root.after(100, self.start_scan)

    def _build(self):
        root = self.root
        px = configure_window(root, self.title)
        self.shell = Workspace(self, self.mode, px)
        page = self.shell.page
        ttk.Label(page, text="날짜별 정리" if self.mode == "date" else self.title,
                  style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(page, text=self.subtitle, style="Subtitle.TLabel").grid(
            row=1, column=0, sticky="w", pady=(px(5), 0))
        controls = ttk.Frame(page)
        controls.grid(row=2, column=0, sticky="ew", pady=(px(24), px(20)))
        controls.columnconfigure(0, weight=1)
        self.folder_entry = ttk.Entry(controls, textvariable=self.folder, state="readonly")
        self.folder_entry.grid(row=0, column=0, sticky="ew", padx=(0, px(10)))
        self.folder_button = ttk.Button(controls, text="폴더 선택", command=self.choose_folder)
        self.folder_button.grid(row=0, column=1)
        self.recursive_button = None
        self.view_button = None
        if self.mode == "date":
            self.recursive_button = ttk.Checkbutton(controls, text="하위 폴더 포함",
                variable=self.recursive, command=self.start_scan)
            self.recursive_button.grid(row=1, column=0, sticky="w", pady=(px(12), 0))
            self.view_button = ttk.Button(controls, text="보기·정렬", style="Text.TButton",
                                          command=self.open_view_settings)
            self.view_button.grid(row=1, column=1, sticky="e", pady=(px(12), 0))
        else:
            ttk.Label(controls, text="JPG → JPG 폴더     NEF → NEF 폴더     MOV → MOV 폴더",
                style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(px(14), 0))
            self.view_button = ttk.Button(controls, text="보기·정렬", style="Text.TButton",
                                          command=self.open_view_settings)
            self.view_button.grid(row=1, column=1, sticky="e", pady=(px(12), 0))

        summary = ttk.Frame(page)
        summary.grid(row=3, column=0, sticky="ew", pady=(0, px(12)))
        summary.columnconfigure(0, weight=1)
        title = ttk.Frame(summary)
        title.grid(row=0, column=0, sticky="w")
        ttk.Label(title, text="미리보기", style="Heading.TLabel").pack(side="left")
        ttk.Label(title, textvariable=self.heading, style="Muted.TLabel").pack(side="left", padx=(px(12), 0))
        self.all_button = ttk.Button(summary, text="전체 선택", style="Text.TButton", command=lambda: self.check_all(True))
        self.all_button.grid(row=0, column=1)
        self.none_button = ttk.Button(summary, text="선택 해제", style="Text.TButton", command=lambda: self.check_all(False))
        self.none_button.grid(row=0, column=2)
        ttk.Label(summary, text=self.detail, style="Muted.TLabel", wraplength=px(790)).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(px(7), 0))
        self.tree, self.empty = file_table(page, [
            ("name", "파일명", 205, True, "w"), ("from", "현재 폴더", 130, True, "w"),
            ("to", "이동할 위치", 240, True, "w"), ("note", "기준 / 결과", 170, True, "w"),
        ], px, "폴더를 선택해 시작하세요\n이동할 위치를 미리 확인할 수 있어요.")
        self.tree.bind("<Button-1>", self._click)
        self.tree.bind("<space>", self._space)
        self.tree.bind("<Double-1>", self._open_file)
        self.tree.bind("<Return>", self._open_file)
        self.tree.bind("<Control-a>", lambda event: (self.check_all(True), "break")[1])
        self.tree.bind("<Control-Shift-A>", lambda event: (self.check_all(False), "break")[1])

        lower = ttk.Frame(page)
        lower.grid(row=5, column=0, sticky="ew", pady=(px(10), px(15)))
        lower.columnconfigure(0, weight=1)
        ttk.Label(lower, textvariable=self.status, style="Muted.TLabel", wraplength=px(650)).grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(lower, mode="indeterminate", length=px(105))
        self.progress.grid(row=0, column=1, padx=(px(12), 0))
        self.progress.grid_remove()
        footer = ttk.Frame(page)
        footer.grid(row=6, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Separator(footer).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, px(15)))
        ttk.Label(footer, textvariable=self.selection_text, style="Selection.TLabel").grid(row=1, column=0, sticky="w")
        self.run_button = ttk.Button(footer, text="선택한 파일 정리하기", style="Primary.TButton", command=self.run)
        self.run_button.grid(row=1, column=1, sticky="e")
        self._controls()

    def _controls(self):
        stage = 3 if self.finished or self.operation in {"run", "view"} else (2 if self.plan is not None or self.busy else 1)
        self.shell.set_state(self.busy, stage)
        self.folder_button.configure(state="disabled" if self.busy else "normal")
        if self.recursive_button:
            self.recursive_button.configure(state="disabled" if self.busy else "normal")
        editable = self.plan is not None and not self.busy and not self.finished
        for button in [self.all_button, self.none_button]:
            button.configure(state="normal" if editable and self.plan.items else "disabled")
        self.run_button.configure(state="normal" if editable and self.checked else "disabled")
        if self.view_button:
            self.view_button.configure(state="normal" if self.plan is not None and not self.busy else "disabled")
        if self.busy:
            self.progress.grid()
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.grid_remove()

    def choose_folder(self):
        if self.busy:
            return
        folder = filedialog.askdirectory(parent=self.root, title="정리할 사진 폴더를 선택하세요", mustexist=True)
        if folder:
            self.folder.set(folder)
            self.start_scan()

    def _job(self, phase, function):
        self.busy, self.operation = True, phase
        self._controls()
        events = self.events
        def work():
            try:
                result = function()
            except Exception as error:
                events.put((phase, False, str(error)))
            else:
                events.put((phase, True, result))
        threading.Thread(target=work, daemon=True, name="PhotoOrganizer-" + phase).start()

    def start_scan(self):
        if self.busy or not self.folder.get():
            return
        target, recursive = Path(self.folder.get()), self.recursive.get()
        mode = self.mode
        self.plan = None
        self.finished = False
        self.checked.clear()
        self.tree.delete(*self.tree.get_children())
        self.heading.set("정리할 파일을 확인하고 있어요")
        self.selection_text.set("")
        self.status.set("촬영 날짜를 확인하는 데 시간이 걸릴 수 있어요." if self.mode == "date" else "파일 종류를 확인하고 있어요.")
        self.empty.configure(text="사진을 확인하고 있어요…")
        self.empty.place(relx=0.5, rely=0.5, anchor="center")
        def scan():
            return jobs.build_plan(target, mode, recursive)
        self._job("scan", scan)

    def _show_plan(self, plan):
        self.plan = plan
        self.folder.set(str(plan.root))
        self.folder_entry.xview_moveto(1)
        self.checked = {index for index, item in enumerate(plan.items) if item.eligible}
        self.tree.delete(*self.tree.get_children())
        for index, item in enumerate(plan.items):
            source_folder = item.source.parent.relative_to(plan.root)
            destination = str(item.destination.relative_to(plan.base)) if item.destination else "—"
            self.tree.insert("", "end", iid=str(index), text="☑" if item.eligible else "—",
                image=checkbox(self.root, True) if item.eligible else "", values=(
                item.source.name, str(source_folder) if str(source_folder) != "." else "선택한 폴더",
                destination, item.reason), tags=(("odd" if index % 2 else "even"),) + (() if item.eligible else ("skipped",)))
        total, skipped = len(self.checked), len(plan.items) - len(self.checked)
        self.heading.set(f"정리할 파일 {total:,}개" + (f" · 건너뜀 {skipped:,}개" if skipped else ""))
        if plan.items:
            self.empty.place_forget()
            self.status.set("이동할 위치를 확인하세요. 남길 파일은 체크를 해제하면 됩니다.")
        else:
            self.empty.configure(text="정리할 파일이 없어요.")
            self.empty.place(relx=0.5, rely=0.5, anchor="center")
            self.status.set("다른 폴더를 선택해 계속 사용할 수 있어요.")
        self._selection_changed()

    def _selection_changed(self):
        self.selection_text.set(f"{len(self.checked):,}개 선택")
        self._controls()

    def check_all(self, checked):
        if self.busy or self.finished or not self.plan:
            return
        self.checked = {i for i, item in enumerate(self.plan.items) if item.eligible} if checked else set()
        for index, item in enumerate(self.plan.items):
            if item.eligible:
                set_checked(self.tree, str(index), index in self.checked)
        self._selection_changed()

    def toggle(self, index):
        if self.busy or self.finished or not self.plan or not self.plan.items[index].eligible:
            return
        if index in self.checked:
            self.checked.remove(index)
        else:
            self.checked.add(index)
        set_checked(self.tree, str(index), index in self.checked)
        self._selection_changed()

    def _click(self, event):
        row = self.tree.identify_row(event.y)
        if row and self.tree.identify_column(event.x) == "#0":
            self.toggle(int(row))
            return "break"

    def _space(self, event):
        if selected := self.tree.selection():
            self.toggle(int(selected[0]))
        return "break"

    def _open_file(self, event):
        if self.busy or not self.plan:
            return "break"
        if getattr(event, "num", None) == 1 and self.tree.identify_column(event.x) == "#0":
            return "break"
        if selected := self.tree.selection():
            item = self.plan.items[int(selected[0])]
            path = item.source if item.source.exists() else item.destination
            try:
                os.startfile(path)
            except (OSError, TypeError) as error:
                messagebox.showerror("파일을 열지 못했어요", str(error), parent=self.root)
        return "break"

    def open_view_settings(self):
        if self.busy or self.plan is None:
            return
        if self.view_dialog is not None:
            self.view_dialog.window.lift()
            return
        self.view_dialog = ExplorerDialog(self)

    def apply_view_settings(self, options):
        if self.busy or self.plan is None:
            return
        self.view_options = options
        target = self.plan.root
        self.status.set("탐색기 보기와 정렬을 적용하고 있어요.")
        self._job("view", lambda: jobs.apply_views(target, options, mode=self.mode))

    def run(self):
        if self.busy or self.finished or not self.plan or not self.checked:
            return
        selected, plan, options = sorted(self.checked), self.plan, self.view_options
        if not messagebox.askyesno("정리할까요?", f"선택한 {len(selected):,}개 파일을 표시된 위치로 정리합니다.\n\n"
            f"대상: {plan.root}", parent=self.root, default="no", icon="question"):
            return
        self.status.set("선택한 파일을 정리하고 있어요.")
        events = self.events
        def progress(position, total, name):
            events.put(("progress", True, f"{position:,}/{total:,}개 · {name}"))
        self._job("run", lambda: jobs.execute(plan, selected, progress=progress, view_options=options))

    def _show_result(self, result):
        self.finished = True
        self.checked.clear()
        for index, item in enumerate(self.plan.items):
            outcome, note = result.rows.get(index, ("미선택" if item.eligible else "건너뜀", item.reason))
            values = list(self.tree.item(str(index), "values"))
            values[-1] = outcome + (" · " + note if note else "")
            self.tree.item(str(index), text="", image="", values=values)
        text = f"이동 {result.moved:,}개"
        if self.mode == "date":
            text += f" / 날짜 맞춤 {result.dates_set:,}개 / NEF 날짜 유지 {result.nef_preserved:,}개"
        if result.skipped or result.failed:
            text += f"\n건너뜀 {result.skipped:,}개 / 오류 {result.failed:,}개"
        if result.view_failed:
            text += f"\n탐색기 보기 설정 실패 {result.view_failed:,}개 폴더"
        self.heading.set("정리를 마쳤어요")
        self.selection_text.set(f"이동 {result.moved:,}개")
        self.status.set("다른 폴더를 선택해 계속 사용할 수 있어요. 각 파일의 결과는 위 목록에서 확인하세요.")
        self._controls()
        show = messagebox.showwarning if result.failed or result.skipped or result.view_failed else messagebox.showinfo
        show("정리 결과", text, parent=self.root)

    def _poll(self):
        if self.closed:
            return
        try:
            while True:
                phase, success, result = self.events.get_nowait()
                if phase == "progress":
                    self.status.set(result)
                    continue
                self.busy, self.operation = False, ""
                self._controls()
                if not success:
                    self.status.set("작업을 중단했어요. 내용을 확인해 주세요.")
                    if phase == "scan":
                        self.heading.set("폴더를 다시 선택해 주세요")
                        self.empty.configure(text="폴더를 확인하지 못했어요.")
                    messagebox.showerror("정리를 중단했어요", result, parent=self.root)
                elif phase == "scan":
                    self._show_plan(result)
                elif phase == "view":
                    applied, failed = result
                    text = f"{len(applied):,}개 폴더의 보기·정렬을 적용했어요."
                    if failed:
                        text += f"\n실패 {len(failed):,}개\n" + "\n".join(f"{p.name}: {error}" for p, error in list(failed.items())[:5])
                    text += "\n\n이미 열린 탐색기는 닫았다가 다시 열어 주세요."
                    self.status.set(f"보기·정렬 적용 {len(applied):,}개 폴더 / 실패 {len(failed):,}개")
                    show = messagebox.showwarning if failed else messagebox.showinfo
                    show("보기·정렬 설정", text, parent=self.root)
                else:
                    self._show_result(result)
        except queue.Empty:
            pass
        if not self.closed:
            self.poll_id = self.root.after(80, self._poll)

    def close(self):
        if self.busy and self.operation in {"run", "view"}:
            messagebox.showinfo("정리 중이에요", "파일 정리가 끝나면 창을 닫아 주세요.", parent=self.root)
            return
        self.closed = True
        cancel_callbacks(self)
        self.root.update_idletasks()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["date", "type"], default="date")
    parser.add_argument("folder", nargs="?", type=Path)
    args = parser.parse_args()
    enable_dpi_awareness()
    root = tk.Tk()
    OrganizerApp(root, args.mode, initial_folder=args.folder)
    root.mainloop()


if __name__ == "__main__":
    main()
