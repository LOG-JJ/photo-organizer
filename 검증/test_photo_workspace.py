"""같은 창의 도구 전환이 폴더와 설정을 이어받고 파일을 건드리지 않는지 확인."""
from pathlib import Path
import gc
import sys
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import photo_organizer_gui as ui
from photo_gui_common import switch_tool
from photo_folder_views import ExplorerOptions

ui.enable_dpi_awareness()


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="photo_workspace_")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name) / "사진 & dates"
        self.folder.mkdir()
        self.photo = self.folder / "keep.NEF"
        self.photo.write_bytes(b"generated navigation fixture")
        self.before = self.photo.read_bytes(), self.photo.stat().st_mtime_ns
        self.root = tk.Tk()
        self.root.withdraw()
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.app = ui.OrganizerApp(self.root)
        self.root.update_idletasks()

    def tearDown(self):
        current = self.root._photo_current_app
        current.busy = False
        if not current.closed:
            current.close()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.before, (self.photo.read_bytes(), self.photo.stat().st_mtime_ns))
        self.assertEqual(list(self.folder.iterdir()), [self.photo])
        self.app = self.root = None
        gc.collect()

    def finish(self, app):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.root.update()
            if not app.busy and app.folder.get() and (getattr(app, "plan", None) is not None or getattr(app, "scan", None) is not None):
                return
            time.sleep(.01)
        self.fail("navigation scan did not finish")

    def test_three_tools_share_window_and_folder(self):
        self.app.folder.set(str(self.folder))
        with patch.object(ui.filedialog, "askdirectory") as picker:
            for tool in ("type", "pair", "date"):
                previous = self.root._photo_current_app
                previous.shell.nav_buttons[tool].invoke()
                current = self.root._photo_current_app
                self.assertIs(current.root, self.root)
                self.assertEqual(current.shell.tool, tool)
                self.assertTrue(previous.closed)
                self.assertEqual(Path(current.folder.get()), self.folder)
                self.finish(current)
                self.assertTrue(current.checked)
            picker.assert_not_called()

    def test_busy_tool_cannot_be_switched(self):
        self.app.busy, self.app.operation = True, "run"
        self.app._controls()
        self.assertTrue(self.app.shell.nav_buttons["pair"].instate(["disabled"]))
        self.app.shell.nav_buttons["pair"].invoke()
        self.assertIsNone(switch_tool(self.app, "pair"))
        self.assertIs(self.root._photo_current_app, self.app)
        self.assertFalse(self.app.closed)

    def test_fast_switch_cancels_old_callbacks_and_keeps_view_options(self):
        self.app.folder.set(str(self.folder))
        self.app.view_options = ExplorerOptions(general_view="목록", auto_apply=False)
        expected = self.app.view_options
        for tool in ("type", "pair", "date"):
            switch_tool(self.root._photo_current_app, tool)
        current = self.root._photo_current_app
        self.finish(current)
        self.assertEqual(current.view_options, expected)

    def test_resize_keeps_actions_visible_in_all_tools(self):
        self.root.deiconify()
        self.root.update()
        minimum_width, minimum_height = self.root.minsize()
        for tool in ("date", "type", "pair"):
            if self.root._photo_current_app.shell.tool != tool:
                switch_tool(self.root._photo_current_app, tool)
            current = self.root._photo_current_app
            for width, height in ((minimum_width, minimum_height),
                                  (minimum_width + 180, minimum_height + 120)):
                self.root.geometry(f"{width}x{height}")
                self.root.update()
                action = getattr(current, "run_button", getattr(current, "recycle_button", None))
                for widget in (current.folder_button, current.all_button, current.none_button, action):
                    self.assertGreaterEqual(widget.winfo_rootx(), self.root.winfo_rootx())
                    self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                         self.root.winfo_rootx() + self.root.winfo_width())
                    self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                         self.root.winfo_rooty() + self.root.winfo_height())
                self.assertGreater(current.tree.winfo_height(), 100)


if __name__ == "__main__":
    unittest.main()
