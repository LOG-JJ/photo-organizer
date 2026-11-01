"""탐색기 설정의 범위, 정렬 방향 및 실제 Windows 저장값을 검증합니다."""
from pathlib import Path
import contextlib
import io
import os
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from _support import ROOT
from photo_organizer.windows import folder_views as views
from photo_organizer.core import dates as dates
from photo_organizer.core import jobs as jobs
class ExplorerSettingsTests(unittest.TestCase):
    def test_direction_uses_signed_windows_values(self):
        self.assertEqual(struct.unpack("<i", views.sort_blob(views.SORT_NAME, True)[-4:])[0], 1)
        self.assertEqual(struct.unpack("<i", views.sort_blob(views.SORT_NAME, False)[-4:])[0], -1)

    def test_default_and_custom_profiles(self):
        defaults = views.ExplorerOptions()
        self.assertEqual(defaults.profile(False), ("자세히", views.SORT_NAME, True))
        self.assertEqual(defaults.profile(True, views.SORT_DATE_MODIFIED), ("아주 큰 아이콘", views.SORT_DATE_MODIFIED, True))
        custom = views.ExplorerOptions(general_view="목록", general_sort="크기", general_ascending=False,
                                       date_view="큰 아이콘", date_sort="찍은 날짜", date_ascending=False)
        self.assertEqual(custom.profile(False), ("목록", views.SORT_SIZE, False))
        self.assertEqual(custom.profile(True), ("큰 아이콘", views.SORT_DATE_TAKEN, False))

    def test_invalid_options_are_rejected(self):
        with self.assertRaises(ValueError):
            views.ExplorerOptions(date_sort="unknown")
        with self.assertRaises(ValueError):
            views.ExplorerOptions(general_view="unknown")

    def test_automatic_can_be_disabled(self):
        with patch.object(dates, "FolderViewStore") as store:
            self.assertEqual(dates.apply_folder_views([], False, views.ExplorerOptions(auto_apply=False)), 0)
            store.assert_not_called()

    def test_manual_applies_inside_selected_root_and_moves_no_files(self):
        with tempfile.TemporaryDirectory(prefix="view_scope_test_") as temporary:
            root = Path(temporary)
            folder = root / "NEF" / "2026-09-25"
            folder.mkdir(parents=True)
            photo = folder / "same.NEF"
            photo.write_bytes(b"original photo fixture")
            before = photo.read_bytes(), photo.stat().st_mtime_ns
            options = views.ExplorerOptions(general_view="목록", general_sort="이름", general_ascending=False,
                                            date_view="큰 아이콘", date_sort="수정한 날짜", date_ascending=False)
            with patch.object(jobs, "FolderViewStore") as store:
                applied, failed = jobs.apply_views(root, options)
                calls = store.return_value.__enter__.return_value.apply.call_args_list
            self.assertEqual(set(applied), {root, folder, folder.parent})
            self.assertFalse(failed)
            by_path = {call.args[0]: call.kwargs for call in calls}
            self.assertEqual(by_path[root], {"view": "목록", "sort_key": views.SORT_NAME, "ascending": False})
            self.assertEqual(by_path[folder], {"view": "큰 아이콘", "sort_key": views.SORT_DATE_MODIFIED, "ascending": False})
            self.assertEqual(before, (photo.read_bytes(), photo.stat().st_mtime_ns))
            self.assertEqual([p for p in root.rglob("*") if p.is_file()], [photo])

    def test_selecting_date_folder_does_not_change_its_parent(self):
        with tempfile.TemporaryDirectory(prefix="view_date_scope_") as temporary:
            folder = Path(temporary) / "2026-09-25"
            folder.mkdir()
            with patch.object(jobs, "FolderViewStore") as store:
                applied, failed = jobs.apply_views(folder, views.ExplorerOptions())
            self.assertEqual(applied, [folder])
            self.assertFalse(failed)

    def test_type_views_apply_only_to_classified_folders(self):
        with tempfile.TemporaryDirectory(prefix="view_type_scope_") as temporary:
            root = Path(temporary)
            paths = []
            for name in ("JPG/keep.JPG", "NEF/keep.NEF", "MOV/keep.MOV", "unrelated/2026-09-25/keep.JPG"):
                photo = root / name
                photo.parent.mkdir(parents=True, exist_ok=True)
                photo.write_bytes(b"original fixture")
                paths.append(photo)
            before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}
            with patch.object(jobs, "FolderViewStore") as store:
                applied, failed = jobs.apply_views(root, views.ExplorerOptions(), mode="type")
                calls = store.return_value.__enter__.return_value.apply.call_args_list
            self.assertFalse(failed)
            self.assertEqual(set(applied), {root/"JPG", root/"NEF", root/"MOV"})
            by_path = {call.args[0]: call.kwargs for call in calls}
            self.assertNotIn(root, by_path)
            for name, sort in (("JPG", views.SORT_DATE_TAKEN), ("NEF", views.SORT_DATE_MODIFIED), ("MOV", views.SORT_DATE_MODIFIED)):
                self.assertEqual(by_path[root/name], {"view":"아주 큰 아이콘", "sort_key":sort, "ascending":True})
            self.assertEqual(before, {p:(p.read_bytes(), p.stat().st_mtime_ns) for p in paths})

    def test_type_automatic_views_never_write_parent_settings(self):
        with tempfile.TemporaryDirectory(prefix="view_type_auto_") as temporary:
            root = Path(temporary)
            for name in ("same.JPG", "same.NEF", "same.MOV"):
                (root/name).write_bytes(b"generated type fixture")
            plan = jobs.build_plan(root, "type")
            with patch.object(dates, "FolderViewStore") as store, contextlib.redirect_stdout(io.StringIO()):
                result = jobs.execute(plan, [0, 1, 2])
                calls = store.return_value.__enter__.return_value.apply.call_args_list
            self.assertEqual(result.moved, 3)
            self.assertEqual({call.args[0] for call in calls}, {root/"JPG", root/"NEF", root/"MOV"})

    def test_custom_options_used_after_date_organization(self):
        with tempfile.TemporaryDirectory(prefix="view_after_date_") as temporary:
            folder = Path(temporary) / "2026-09-25"
            folder.mkdir()
            photo = folder / "same.NEF"
            photo.write_bytes(b"fixture")
            options = views.ExplorerOptions(general_view="목록", general_ascending=False,
                                            date_view="작은 아이콘", date_sort="크기", date_ascending=False)
            with patch.object(dates, "FolderViewStore") as store, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(dates.apply_folder_views([photo], False, options), 0)
                calls = store.return_value.__enter__.return_value.apply.call_args_list
            by_path = {call.args[0]: call.kwargs for call in calls}
            self.assertEqual(by_path[folder], {"view": "작은 아이콘", "sort_key": views.SORT_SIZE, "ascending": False})

    @unittest.skipUnless(os.name == "nt", "Windows view property bag")
    def test_native_view_modes_and_descending_saved_without_files(self):
        with tempfile.TemporaryDirectory(prefix="view_native_test_") as temporary:
            folder = Path(temporary)
            with views.FolderViewStore() as store:
                for label, (mode, logical, size) in views.VIEW_MODES.items():
                    with self.subTest(view=label):
                        store.apply(folder, view=label, sort_key=views.SORT_SIZE, ascending=False)
                        values = store.read_values(folder, "Shell", ["Mode", "LogicalViewMode", "IconSize", "Sort"])
                        self.assertEqual((values["Mode"], values["LogicalViewMode"], values["IconSize"]), (mode, logical, size))
                        self.assertEqual(values["Sort"], views.sort_blob(views.SORT_SIZE, False))
            self.assertEqual(list(folder.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
