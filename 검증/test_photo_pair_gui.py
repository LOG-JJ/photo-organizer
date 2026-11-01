"""임시 파일 및 숨겨진 Tk 창으로 GUI 동작을 검증합니다."""
from pathlib import Path
import sys
import gc
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import photo_pair_cleanup_gui as ui
ui.enable_dpi_awareness()


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pair_gui_test_")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / "photos & dates"
        self.folder.mkdir()
        self.root = tk.Tk()
        self.root.withdraw()
        self.root._photo_pair_mode = "JPG를 먼저 정리했어요 → 남은 RAW 찾기"
        picker = patch.object(ui.filedialog, "askdirectory", return_value="")
        self.picker = picker.start()
        self.addCleanup(picker.stop)
        self.app = ui.PhotoCleanupApp(self.root)
        self.root.update_idletasks()
        for name in ["showerror", "showinfo", "showwarning"]:
            patcher = patch.object(ui.messagebox, name)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def tearDown(self):
        self.app.busy = False
        if not self.app.closed:
            self.root.update_idletasks()
            self.app.close()
        self.app = self.root = None
        gc.collect()

    def photo(self, name):
        path = self.folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"generated GUI test photo")
        return path

    def finish_jobs(self):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            self.root.update()
            if not self.app.busy and self.app.events.empty():
                return
            time.sleep(0.01)
        self.fail("GUI background job timed out")

    def scan(self):
        self.app.folder.set(str(self.folder))
        self.app.start_scan()
        self.finish_jobs()

    def test_initial_buttons(self):
        deadline = time.monotonic() + 0.25
        while time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.picker.assert_not_called()
        self.assertTrue(self.app.recycle_button.instate(["disabled"]))
        self.assertFalse(hasattr(self.app, "records_button"))
        self.assertEqual(self.app.kind, "both")
        self.assertFalse(hasattr(self.app, "mode_box"))
        self.assertFalse(hasattr(self.app, "mode"))
        self.app.folder_button.invoke()
        self.picker.assert_called_once()

    def test_choose_folder_automatically_scans_and_checks_candidates(self):
        self.photo("DSC_001.NEF")
        self.photo("keep.NEF")
        self.photo("keep.JPG")
        with patch.object(ui.filedialog, "askdirectory", return_value=str(self.folder)):
            self.app.choose_folder()
        self.finish_jobs()
        self.assertEqual(self.app.checked, {0})
        self.assertEqual(self.app.tree.item("0", "values")[0], "DSC_001.NEF")
        self.assertTrue(self.app.recycle_button.instate(["!disabled"]))
        self.assertIn("1개", self.app.heading.get())

    def test_folder_picker_cancel_does_nothing(self):
        with patch.object(ui.filedialog, "askdirectory", return_value=""):
            self.app.choose_folder()
        self.assertFalse(self.app.busy)
        self.assertIsNone(self.app.scan)

    def test_toggle_and_select_all(self):
        self.photo("DSC_001.NEF")
        self.photo("DSC_002.NEF")
        self.scan()
        self.app.check_all(False)
        self.assertEqual(self.app.checked, set())
        self.assertTrue(self.app.recycle_button.instate(["disabled"]))
        self.app.toggle(1)
        self.assertEqual(self.app.checked, {1})
        self.assertEqual(self.app.tree.item("1", "text"), "☑")
        self.app.check_all(True)
        self.assertEqual(self.app.checked, {0, 1})

    def test_search_always_includes_raw_and_jpg_orphans(self):
        self.photo("raw_only.NEF")
        self.photo("jpg_only.JPG")
        self.scan()
        self.assertEqual(self.app.kind, "both")
        self.assertEqual({p.path.name for p in self.app.scan.candidates}, {"raw_only.NEF", "jpg_only.JPG"})
        self.assertEqual(len(self.app.checked), 2)

    def test_no_orphans_disables_recycle(self):
        self.photo("keep.NEF")
        self.photo("keep.JPG")
        self.scan()
        self.assertFalse(self.app.scan.candidates)
        self.assertTrue(self.app.recycle_button.instate(["disabled"]))
        self.assertIn("정리할 사진이 없습니다", self.app.empty.cget("text"))

    def test_parent_jpg_copy_with_dated_raw_is_excluded_and_explained(self):
        self.photo("DSC_3710.JPG")
        self.photo("JPG/2026-09-26/DSC_3710.JPG")
        self.photo("RAW/2026-09-26/DSC_3710.NEF")
        self.scan()
        self.assertFalse(self.app.scan.candidates)
        self.assertEqual(len(self.app.scan.protected), 1)
        self.assertFalse(self.app.tree.get_children())
        self.assertTrue(self.app.recycle_button.instate(["disabled"]))
        self.assertIn("상위·하위 폴더", self.app.status.get())
        self.assertIn("1개는 제외", self.app.status.get())

    def test_selecting_raw_folder_compares_sibling_jpg(self):
        self.photo("RAW/keep.NEF")
        self.photo("JPG/keep.JPG")
        self.app.folder.set(str(self.folder / "RAW"))
        self.app.start_scan()
        self.finish_jobs()
        self.assertEqual(self.app.scan.root, self.folder)
        self.assertEqual(self.app.scan.pairs, 1)
        self.assertIn("상위 폴더", self.app.status.get())

    def test_selecting_nested_date_folder_compares_both_formats(self):
        self.photo("RAW/2026-09-26/DSC_3710.NEF")
        self.photo("JPG/2026-09-26/DSC_3710.JPG")
        self.app.folder.set(str(self.folder / "RAW" / "2026-09-26"))
        self.app.start_scan()
        self.finish_jobs()
        self.assertIsNotNone(self.app.scan)
        self.assertEqual(self.app.scan.root, self.folder)
        self.assertFalse(self.app.scan.candidates)
        self.showerror.assert_not_called()

    def test_selecting_raw_folder_also_compares_jpg_in_parent(self):
        self.photo("RAW/DSC_3710.NEF")
        self.photo("DSC_3710.JPG")
        self.app.folder.set(str(self.folder / "RAW"))
        self.app.start_scan()
        self.finish_jobs()
        self.assertEqual(self.app.scan.root, self.folder)
        self.assertFalse(self.app.scan.candidates)
        self.assertTrue(self.app.recycle_button.instate(["disabled"]))

    def test_cancel_confirmation_preserves_files(self):
        photo = self.photo("orphan.NEF")
        self.scan()
        with patch.object(ui.messagebox, "askyesno", return_value=False) as confirm, \
             patch.object(ui.core, "recycle_selected") as recycle:
            self.app.recycle()
            self.assertEqual(confirm.call_args.kwargs["default"], "no")
            recycle.assert_not_called()
        self.assertTrue(photo.exists())

    def test_only_checked_files_are_sent_without_record_files(self):
        self.photo("first.NEF")
        self.photo("second.NEF")
        self.scan()
        self.app.toggle(0)
        with patch.object(ui.messagebox, "askyesno", return_value=True), \
             patch.object(ui.core, "recycle_selected", return_value=(1, 0)) as recycle:
            self.app.recycle()
            self.assertTrue(self.app.folder_button.instate(["disabled"]))
            self.finish_jobs()
            self.assertEqual(recycle.call_args.args[1], [1])
            self.assertIsInstance(recycle.call_args.kwargs["messages"], list)
        self.assertFalse(list(Path(self.temp.name).rglob("*.csv")))
        self.showinfo.assert_called_once()

    def test_read_error_restores_controls(self):
        self.app.folder.set(str(self.folder))
        with patch.object(ui.core, "scan_folder", side_effect=OSError("test read error")):
            self.app.start_scan()
            self.finish_jobs()
        self.showerror.assert_called_once()
        self.assertFalse(self.app.busy)
        self.assertTrue(self.app.folder_button.instate(["!disabled"]))
        self.assertTrue(self.app.recycle_button.instate(["disabled"]))

    def test_close_waits_for_recycle(self):
        self.app.busy, self.app.operation = True, "recycle"
        self.app.close()
        self.assertFalse(self.app.closed)
        self.showinfo.assert_called_once()


if __name__ == "__main__":
    unittest.main()
