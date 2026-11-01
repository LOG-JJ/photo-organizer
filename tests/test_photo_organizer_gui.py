"""프로그램 시작, 폴더 선택, 취소 및 임시 파일 실제 정리 흐름을 검증합니다."""
from pathlib import Path
import contextlib
import gc
from datetime import datetime
import io
import os
import sys
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from _support import ROOT
from photo_organizer.ui import organizer as ui
ui.enable_dpi_awareness()


class OrganizerGuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="organizer_gui_test_")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / "photos & dates"
        self.folder.mkdir()
        silence = contextlib.redirect_stdout(io.StringIO())
        silence.__enter__()
        self.addCleanup(silence.__exit__, None, None, None)
        for name in ["showerror", "showwarning", "showinfo", "askyesno"]:
            patcher = patch.object(ui.messagebox, name, return_value=False)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        picker = patch.object(ui.filedialog, "askdirectory", return_value="")
        self.picker = picker.start()
        self.addCleanup(picker.stop)
        for name in ["shell_metadata_dates", "apply_folder_views"]:
            patcher = patch.object(ui.jobs.dates, name, return_value={} if name == "shell_metadata_dates" else 0)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.root = self.app = None
        self.make_app()

    def make_app(self, mode="date"):
        if self.app:
            self.app.busy = False
            self.root.update_idletasks()
            self.app.close()
            self.app = self.root = None
            gc.collect()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = ui.OrganizerApp(self.root, mode)
        self.root.update_idletasks()

    def tearDown(self):
        self.assertFalse(list(Path(self.temp.name).rglob("*.csv")))
        self.assertFalse(hasattr(self.app, "records_button"))
        self.app.busy = False
        if not self.app.closed:
            self.root.update_idletasks()
            self.app.close()
        self.app = self.root = None
        gc.collect()

    def photo(self, name, data=b"generated GUI fixture"):
        path = self.folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def finish_jobs(self):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            self.root.update()
            if not self.app.busy and self.app.events.empty():
                return
            time.sleep(0.01)
        self.fail("background work timed out")

    def scan(self):
        self.app.folder.set(str(self.folder))
        self.app.start_scan()
        self.finish_jobs()

    def test_both_apps_wait_for_folder_button(self):
        for mode in ["date", "type"]:
            with self.subTest(mode=mode):
                self.make_app(mode)
                self.picker.reset_mock()
                deadline = time.monotonic() + 0.22
                while time.monotonic() < deadline:
                    self.root.update()
                    time.sleep(0.01)
                self.picker.assert_not_called()
                self.assertTrue(self.app.run_button.instate(["disabled"]))
                self.app.folder_button.invoke()
                self.picker.assert_called_once()

    def test_date_preview_does_not_move_files(self):
        source = self.photo("DSC.NEF")
        unknown = self.photo("unknown.JPG")
        before = source.read_bytes(), source.stat().st_mtime_ns
        self.picker.return_value = str(self.folder)
        self.app.folder_button.invoke()
        self.finish_jobs()
        self.assertEqual(len(self.app.plan.items), 2)
        self.assertEqual(len(self.app.checked), 1)
        self.assertEqual(before, (source.read_bytes(), source.stat().st_mtime_ns))
        self.assertTrue(unknown.exists())
        self.assertEqual(len(list(self.folder.iterdir())), 2)

    def test_recursive_checkbox_rebuilds_preview(self):
        self.photo("top.NEF")
        self.photo("nested/inside.NEF")
        self.scan()
        self.assertEqual(len(self.app.plan.items), 2)
        self.app.recursive_button.invoke()
        self.finish_jobs()
        self.assertFalse(self.app.recursive.get())
        self.assertEqual(len(self.app.plan.items), 1)

    def test_cancel_confirmation_preserves_files(self):
        self.make_app("type")
        source = self.photo("same.JPG")
        self.scan()
        with patch.object(ui.jobs, "execute") as execute:
            self.app.run_button.invoke()
            execute.assert_not_called()
        self.assertEqual(self.askyesno.call_args.kwargs["default"], "no")
        self.assertTrue(source.exists())

    def test_type_run_moves_only_checked_file(self):
        self.make_app("type")
        first = self.photo("first.JPG", b"keep")
        second = self.photo("second.NEF", b"move")
        self.scan()
        self.app.toggle(0)
        self.askyesno.return_value = True
        self.app.run_button.invoke()
        self.finish_jobs()
        self.assertTrue(first.exists())
        self.assertFalse(second.exists())
        self.assertEqual((self.folder / "NEF" / second.name).read_bytes(), b"move")
        self.assertTrue(self.app.finished)
        self.assertTrue(self.app.run_button.instate(["disabled"]))
        self.showinfo.assert_called_once()
        self.picker.assert_not_called()

    def test_date_run_preserves_nef_timestamp(self):
        source = self.photo("same.NEF")
        stamp = int(datetime(2026, 9, 25, 10, 0, 0).timestamp()) * 10**9 + 123456700
        os.utime(source, ns=(stamp, stamp))
        original_ns = source.stat().st_mtime_ns
        self.scan()
        self.askyesno.return_value = True
        self.app.run_button.invoke()
        self.finish_jobs()
        destination = self.folder / "2026-09-25" / source.name
        self.assertEqual(destination.stat().st_mtime_ns, original_ns)
        self.assertTrue(self.app.finished)

    def test_duplicate_is_not_selectable(self):
        self.make_app("type")
        self.photo("same.JPG")
        self.photo("JPG/same.JPG", b"existing")
        self.scan()
        self.app.check_all(True)
        self.app.toggle(0)
        self.assertFalse(self.app.checked)
        self.assertTrue(self.app.run_button.instate(["disabled"]))

    def test_read_error_restores_controls(self):
        self.app.folder.set(str(self.folder))
        with patch.object(ui.jobs, "build_plan", side_effect=OSError("test read error")):
            self.app.start_scan()
            self.finish_jobs()
        self.showerror.assert_called_once()
        self.assertTrue(self.app.folder_button.instate(["!disabled"]))
        self.assertTrue(self.app.run_button.instate(["disabled"]))

    def test_run_cannot_be_closed_mid_move(self):
        self.app.busy, self.app.operation = True, "run"
        self.app.close()
        self.assertFalse(self.app.closed)
        self.showinfo.assert_called_once()

    def test_view_dialog_applies_choices_without_organizing_files(self):
        photo = self.photo("same.NEF")
        self.scan()
        self.assertTrue(self.app.view_button.instate(["!disabled"]))
        with patch.object(tk.Toplevel, "grab_set"):
            self.app.open_view_settings()
        dialog = self.app.view_dialog
        dialog.values["general_view"].set("목록")
        dialog.values["date_sort"].set("수정한 날짜")
        dialog.values["date_order"].set("내림차순")
        dialog.auto_apply.set(False)
        with patch.object(ui.jobs, "apply_views", return_value=([self.folder], {})) as apply, \
             patch.object(ui.jobs, "execute") as organize:
            dialog.apply_button.invoke()
            self.finish_jobs()
            self.assertEqual(apply.call_args.args[0], self.folder)
            options = apply.call_args.args[1]
            self.assertEqual(options.general_view, "목록")
            self.assertEqual(options.date_sort, "수정한 날짜")
            self.assertFalse(options.date_ascending)
            self.assertFalse(options.auto_apply)
            organize.assert_not_called()
        self.assertTrue(photo.exists())
        self.assertIsNone(self.app.view_dialog)

    def test_view_dialog_cancel_discards_changes(self):
        self.photo("same.NEF")
        self.scan()
        before = self.app.view_options
        with patch.object(tk.Toplevel, "grab_set"):
            self.app.open_view_settings()
        self.app.view_dialog.values["date_view"].set("목록")
        self.app.view_dialog.cancel_button.invoke()
        self.assertEqual(self.app.view_options, before)
        self.assertFalse(self.app.busy)

    def test_auto_view_setting_can_be_disabled_during_file_move(self):
        self.photo("same.NEF")
        self.scan()
        self.app.view_options = ui.ExplorerOptions(auto_apply=False)
        self.askyesno.return_value = True
        with patch.object(ui.jobs.dates, "apply_folder_views") as apply:
            self.app.run()
            self.finish_jobs()
            apply.assert_not_called()

    def test_file_type_app_has_view_settings_without_record_button(self):
        self.make_app("type")
        self.assertIsNotNone(self.app.view_button)
        self.photo("same.JPG")
        self.scan()
        with patch.object(tk.Toplevel, "grab_set"):
            self.app.view_button.invoke()
        with patch.object(ui.jobs, "apply_views", return_value=([self.folder], {})) as apply:
            self.assertNotIn("general_view", self.app.view_dialog.values)
            self.app.view_dialog.apply_button.invoke()
            self.finish_jobs()
            self.assertEqual(apply.call_args.kwargs["mode"], "type")
        self.assertFalse(hasattr(self.app, "records_button"))


if __name__ == "__main__":
    unittest.main()
