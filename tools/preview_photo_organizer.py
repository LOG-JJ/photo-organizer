"""임시 사진으로 정리 프로그램 화면을 확인합니다. 실제 보관 사진은 사용하지 않습니다."""
from pathlib import Path
from datetime import datetime
import json
import os
import sys
import tempfile
import tkinter as tk

from _support import ROOT
from photo_organizer.ui import organizer as ui
mode = sys.argv[1] if len(sys.argv) > 1 else "date"
from photo_organizer.paths import artifact_path
artifact = artifact_path("previews")
close_flag = artifact / ("organizer_preview_close_" + mode)
close_flag.unlink(missing_ok=True)
with tempfile.TemporaryDirectory(prefix="organizer_preview_") as temporary:
    base = Path(temporary)
    folder = base / "화면 확인용 임시 사진"
    folder.mkdir()
    for name in ["DSC_1234.NEF", "DSC_5678.NEF", "20260925_125500.JPG", "20260925_135100.JPG", "20260926_094000.MOV", "20260926_151000.MOV"]:
        path = folder / name
        path.write_bytes(b"generated preview fixture")
        stamp = datetime(2026, 9, 25, 12, 34).timestamp()
        os.utime(path, (stamp, stamp))
    ui.enable_dpi_awareness()
    root = tk.Tk()
    app = ui.OrganizerApp(root, mode)
    root.title(app.title + " — 화면 확인용")
    root.update_idletasks()
    root.geometry(f"+{(root.winfo_screenwidth()-root.winfo_width())//2}+{(root.winfo_screenheight()-root.winfo_height())//2}")
    root.attributes("-topmost", True)
    app.folder.set(str(folder))
    app.start_scan()
    def ready():
        if app.busy:
            root.after(100, ready)
            return
        root.update_idletasks()
        if len(sys.argv) > 2 and sys.argv[2] == "settings":
            app.open_view_settings()
            root.update_idletasks()
        region = [root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height()]
        (artifact / "organizer_preview_region.json").write_text(json.dumps({"region": region}), encoding="utf-8")
        print("PREVIEW_READY", mode, flush=True)
    def check_close():
        if close_flag.exists():
            close_flag.unlink()
            app.close()
        elif not app.closed:
            root.after(250, check_close)
    root.after(500, ready)
    root.after(250, check_close)
    root.after(90000, app.close)
    root.mainloop()
