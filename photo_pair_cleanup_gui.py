"""RAW/JPG 정리의 간단한 Windows 화면. 파일 비교/휴지통 처리는 기존 모듈 사용."""
from __future__ import annotations

import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from photo_gui_common import configure_window, enable_dpi_awareness, Workspace, file_table, checkbox, set_checked, cancel_callbacks

import photo_pair_cleanup as core

def common_folder(path: Path) -> tuple[Path, str]:
    """RAW/JPG 폴더를 골랐을 때는 함께 비교할 상위 폴더를 보여 줍니다."""
    target = core.comparison_root(path)
    if target != path:
        return target, "RAW와 JPG를 함께 비교하도록 상위 폴더를 선택했어요."
    return path, ""


class PhotoCleanupApp:
    kind = "both"

    def __init__(self, root: tk.Tk, initial_folder: Path | None = None):
        self.root = root
        self.scan: core.Scan | None = None
        self.checked: set[int] = set()
        self.busy = False
        self.operation = ""
        self.events: queue.Queue = queue.Queue()
        self.closed = False
        self.folder = tk.StringVar(root, "")
        self.heading = tk.StringVar(root, "폴더를 선택해 주세요")
        self.status = tk.StringVar(root, "하위 폴더도 함께 확인합니다.")
        self.selection_text = tk.StringVar(root, "")
        self.action_text = tk.StringVar(root, "선택한 파일 휴지통으로")
        self._build()
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = root.after(80, self._poll)
        self.initial_scan_id = None
        if initial_folder:
            self.folder.set(str(initial_folder))
            self.initial_scan_id = root.after(100, self.start_scan)

    def _build(self):
        root = self.root
        px = configure_window(root, "RAW · JPG 정리")
        self.shell = Workspace(self, "pair", px)
        page = self.shell.page
        ttk.Label(page, text="RAW · JPG 정리", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(page, text="RAW와 JPG를 함께 비교해, 짝이 없는 사진을 찾아요.",
                  style="Subtitle.TLabel").grid(row=1, column=0, sticky="w", pady=(px(5), 0))
        controls = ttk.Frame(page)
        controls.grid(row=2, column=0, sticky="ew", pady=(px(24), px(20)))
        controls.columnconfigure(0, weight=1)
        self.folder_entry = ttk.Entry(controls, textvariable=self.folder, state="readonly")
        self.folder_entry.grid(row=0, column=0, sticky="ew", padx=(0, px(10)))
        self.folder_button = ttk.Button(controls, text="폴더 선택", command=self.choose_folder)
        self.folder_button.grid(row=0, column=1)

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
        ttk.Label(summary, text="처음부터 한 형식으로만 촬영한 사진도 포함됩니다. 목록을 확인하세요.",
                  style="Muted.TLabel", wraplength=px(790)).grid(row=1, column=0, columnspan=3, sticky="w", pady=(px(7), 0))
        self.tree, self.empty = file_table(page, [
            ("name", "파일명", 245, True, "w"), ("type", "종류", 65, False, "center"),
            ("folder", "폴더", 345, True, "w"), ("size", "크기", 95, False, "e"),
        ], px, "폴더를 선택해 시작하세요\n짝이 없는 사진을 미리 확인할 수 있어요.")
        self.tree.bind("<Button-1>", self._click)
        self.tree.bind("<space>", self._space)
        self.tree.bind("<Double-1>", self._open_photo)
        self.tree.bind("<Return>", self._open_photo)
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
        self.recycle_button = ttk.Button(footer, textvariable=self.action_text,
                                         style="Primary.TButton", command=self.recycle)
        self.recycle_button.grid(row=1, column=1, sticky="e")
        self._refresh_controls()

    def _refresh_controls(self):
        stage = 3 if self.operation == "recycle" else (2 if self.scan is not None or self.busy else 1)
        self.shell.set_state(self.busy, stage)
        self.folder_button.configure(state="disabled" if self.busy else "normal")
        has_rows = bool(self.scan and self.scan.candidates) and not self.busy
        for button in [self.all_button, self.none_button]:
            button.configure(state="normal" if has_rows else "disabled")
        self.recycle_button.configure(state="normal" if has_rows and self.checked else "disabled")
        if self.busy:
            self.progress.grid()
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.grid_remove()

    def choose_folder(self):
        if self.busy:
            return
        folder = filedialog.askdirectory(parent=self.root, title="RAW와 JPG가 함께 있는 폴더를 선택하세요",
                                         mustexist=True)
        if folder:
            self.folder.set(folder)
            self.start_scan()

    def _start_job(self, name, function):
        self.busy, self.operation = True, name
        self._refresh_controls()
        events = self.events
        def work():
            try:
                result = function()
            except Exception as error:
                events.put((name, False, str(error)))
            else:
                events.put((name, True, result))
        threading.Thread(target=work, daemon=True, name="PhotoPair-" + name).start()

    def start_scan(self):
        if self.busy or not self.folder.get():
            return
        folder = Path(self.folder.get())
        kind = self.kind
        self.scan = None
        self.checked.clear()
        self.tree.delete(*self.tree.get_children())
        self.empty.configure(text="짝이 없는 사진을 찾고 있어요…")
        self.empty.place(relx=0.5, rely=0.5, anchor="center")
        self.heading.set("사진을 확인하고 있어요")
        self.selection_text.set("")
        self.status.set("폴더를 읽는 동안 잠시 기다려 주세요.")
        def scan():
            target, notice = common_folder(folder)
            result = core.scan_folder(target, kind)
            return result, notice
        self._start_job("scan", scan)

    def _show_scan(self, scan, notice=""):
        self.scan = scan
        self.folder.set(str(scan.root))
        self.folder_entry.xview_moveto(1)
        self.tree.delete(*self.tree.get_children())
        self.checked = set(range(len(scan.candidates)))
        for index, photo in enumerate(scan.candidates):
            relative = photo.path.parent.relative_to(scan.root)
            folder_label = str(relative) if str(relative) != "." else "선택한 폴더"
            self.tree.insert("", "end", iid=str(index), text="☑", image=checkbox(self.root, True), values=(
                photo.path.name, photo.kind.upper(), folder_label, core.format_size(photo.identity[2])),
                tags=("odd" if index % 2 else "even",))
        count = len(scan.candidates)
        self.heading.set(f"짝이 없는 사진 {count:,}개")
        if count:
            self.empty.place_forget()
            self.status.set(notice or "사진을 열려면 두 번 클릭하세요. 남길 사진은 체크를 해제하세요.")
        else:
            self.empty.configure(text="짝이 없는 파일이 없어요.\n정리할 사진이 없습니다.")
            self.empty.place(relx=0.5, rely=0.5, anchor="center")
            self.status.set(notice or f"검색 완료 · 정상적인 RAW·JPG 쌍 {scan.pairs:,}개")
        if scan.protected:
            self.status.set(self.status.get() +
                f"\n상위·하위 폴더에 같은 이름의 반대 형식이 있는 {len(scan.protected):,}개는 제외했어요.")
        self._selection_changed()

    def _selection_changed(self):
        if self.scan:
            size = sum(self.scan.candidates[index].identity[2] for index in self.checked)
            self.selection_text.set(f"{len(self.checked):,}개 선택 · {core.format_size(size)}")
        self._refresh_controls()

    def check_all(self, checked: bool):
        if self.busy or not self.scan:
            return
        self.checked = set(range(len(self.scan.candidates))) if checked else set()
        for item in self.tree.get_children():
            set_checked(self.tree, item, checked)
        self._selection_changed()

    def toggle(self, index: int):
        if self.busy or not self.scan or not 0 <= index < len(self.scan.candidates):
            return
        if index in self.checked:
            self.checked.remove(index)
        else:
            self.checked.add(index)
        set_checked(self.tree, str(index), index in self.checked)
        self._selection_changed()

    def _click(self, event):
        item = self.tree.identify_row(event.y)
        if item and self.tree.identify_column(event.x) == "#0":
            self.toggle(int(item))
            return "break"

    def _space(self, event):
        if selected := self.tree.selection():
            self.toggle(int(selected[0]))
        return "break"

    def _open_photo(self, event):
        if self.busy or not self.scan:
            return "break"
        if getattr(event, "num", None) == 1 and self.tree.identify_column(event.x) == "#0":
            return "break"
        selected = self.tree.selection()
        if selected:
            try:
                os.startfile(self.scan.candidates[int(selected[0])].path)
            except OSError as error:
                messagebox.showerror("사진을 열지 못했어요", str(error), parent=self.root)
        return "break"

    def recycle(self):
        if self.busy or not self.scan or not self.checked:
            return
        selected = sorted(self.checked)
        scan, kind = self.scan, self.kind
        size = sum(scan.candidates[index].identity[2] for index in selected)
        if not messagebox.askyesno("휴지통으로 보낼까요?",
            f"선택한 {len(selected):,}개 ({core.format_size(size)})를 휴지통으로 보냅니다.\n\n"
            "필요하면 Windows 휴지통에서 복원할 수 있어요.", parent=self.root, default="no", icon="question"):
            return
        self.status.set("선택한 사진을 다시 확인하고 휴지통으로 보내고 있어요.")
        self.action_text.set("정리하는 중…")
        def recycle():
            messages = []
            completed, skipped = core.recycle_selected(scan, selected, kind, messages=messages)
            return completed, skipped, len(selected) - completed - skipped, messages
        self._start_job("recycle", recycle)

    def _poll(self):
        if self.closed:
            return
        try:
            while True:
                operation, success, result = self.events.get_nowait()
                self.busy = False
                self.operation = ""
                self.action_text.set("선택한 파일 휴지통으로")
                self._refresh_controls()
                if not success:
                    self.status.set("작업을 중단했어요. 내용을 확인해 주세요.")
                    if operation == "scan":
                        self.heading.set("폴더를 다시 선택해 주세요")
                        self.empty.configure(text="폴더를 확인하지 못했어요.\n다른 폴더를 선택해 주세요.")
                    messagebox.showerror("폴더를 확인해 주세요" if operation == "scan" else "정리를 중단했어요",
                                         result, parent=self.root)
                elif operation == "scan":
                    self._show_scan(*result)
                else:
                    completed, skipped, untouched, messages = result
                    text = f"{completed:,}개를 휴지통으로 보냈어요."
                    if skipped or untouched:
                        text += f"\n건너뜀·오류 {skipped:,}개 / 미실행 {untouched:,}개"
                        if messages:
                            text += "\n\n" + "\n".join(messages[:8])
                        messagebox.showwarning("정리 결과", text, parent=self.root)
                    else:
                        messagebox.showinfo("정리 완료", text, parent=self.root)
                    self.start_scan()
        except queue.Empty:
            pass
        if not self.closed:
            self.poll_id = self.root.after(80, self._poll)

    def close(self):
        if self.busy and self.operation == "recycle":
            messagebox.showinfo("정리 중이에요", "사진 정리가 끝나면 창을 닫아 주세요.", parent=self.root)
            return
        self.closed = True
        cancel_callbacks(self)
        self.root.update_idletasks()
        self.root.destroy()


def main():
    enable_dpi_awareness()
    root = tk.Tk()
    initial = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    PhotoCleanupApp(root, initial_folder=initial)
    root.mainloop()


if __name__ == "__main__":
    main()
