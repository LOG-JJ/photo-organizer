"""임시 사진 목록으로 실제 창을 띄워 화면을 확인합니다. 45초 후 자동 종료."""
from pathlib import Path
import json
import sys
import tempfile
import tkinter as tk

from _support import ROOT
from photo_organizer.ui import pairs as ui
with tempfile.TemporaryDirectory(prefix="pair_gui_preview_") as temporary:
    base = Path(temporary)
    folder = base / "화면 확인용 임시 사진"
    for number in [1234, 1237, 1241, 1250, 1258, 1263]:
        path = folder / "RAW" / "2026-09-25" / f"DSC_{number}.NEF"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as stream:
            stream.truncate(3 * 1024 * 1024)
    ui.enable_dpi_awareness()
    root = tk.Tk()
    app = ui.PhotoCleanupApp(root)
    root.title("RAW · JPG 정리 — 화면 확인용")
    root.update_idletasks()
    left = (root.winfo_screenwidth() - root.winfo_width()) // 2
    top = (root.winfo_screenheight() - root.winfo_height()) // 2
    root.geometry(f"+{left}+{top}")
    app.folder.set(str(folder))
    app.start_scan()
    root.attributes("-topmost", True)
    def ready():
        if app.busy:
            root.after(100, ready)
            return
        root.update_idletasks()
        region = [root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height()]
        from photo_organizer.paths import artifact_path
        target = artifact_path("previews", "photo_pair_gui_qa_region.json")
        target.write_text(json.dumps({"region": region}), encoding="utf-8")
        print(str(target), flush=True)
    root.after(500, ready)
    root.after(45000, app.close)
    root.mainloop()
