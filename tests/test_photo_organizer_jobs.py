"""정리 예정표, 충돌 방지, 날짜 유지 및 이동을 임시 파일로 검증합니다."""
from pathlib import Path
import contextlib
from datetime import datetime
import io
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from _support import ROOT
from photo_organizer.core import jobs as jobs
class OrganizerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="organizer_test_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "사진 & 행사"
        self.root.mkdir()
        silence = contextlib.redirect_stdout(io.StringIO())
        silence.__enter__()
        self.addCleanup(silence.__exit__, None, None, None)
        metadata = patch.object(jobs.dates, "shell_metadata_dates", return_value={})
        metadata.start()
        self.addCleanup(metadata.stop)
        views = patch.object(jobs.dates, "apply_folder_views", return_value=0)
        self.views = views.start()
        self.addCleanup(views.stop)

    def photo(self, name, data=b"generated test data"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def run_plan(self, plan):
        selected = [i for i, item in enumerate(plan.items) if item.eligible]
        return jobs.execute(plan, selected)

    def test_type_keeps_other_extensions_and_subfolders(self):
        for name in ["DSC.JpG", "DSC.NEF", "clip.MOV", "keep.jpeg", "keep.MP4", "nested/keep.JPG"]:
            self.photo(name, name.encode())
        plan = jobs.build_plan(self.root, "type")
        self.assertEqual(len(plan.items), 3)
        self.assertFalse((self.root / "JPG").exists())
        result = self.run_plan(plan)
        self.assertEqual((result.moved, result.failed), (3, 0))
        for name, folder in [("DSC.JpG", "JPG"), ("DSC.NEF", "NEF"), ("clip.MOV", "MOV")]:
            self.assertEqual((self.root / folder / name).read_bytes(), name.encode())
        for name in ["keep.jpeg", "keep.MP4", "nested/keep.JPG"]:
            self.assertTrue((self.root / name).exists())
        self.assertFalse(list(Path(self.temp.name).rglob("*.csv")))
        self.views.assert_called_once()
        self.assertEqual({p.parent.name for p in self.views.call_args.args[0]}, {"JPG", "NEF", "MOV"})

    def test_type_existing_duplicate_is_left_in_place(self):
        original = self.photo("same.JPG", b"original")
        existing = self.photo("JPG/same.JPG", b"existing")
        plan = jobs.build_plan(self.root, "type")
        self.assertFalse(plan.items[0].eligible)
        self.assertEqual(original.read_bytes(), b"original")
        self.assertEqual(existing.read_bytes(), b"existing")

    def test_type_view_options_can_be_disabled_without_changing_timestamps(self):
        from photo_organizer.windows.folder_views import ExplorerOptions
        photo = self.photo("same.NEF")
        before = photo.stat().st_mtime_ns
        plan = jobs.build_plan(self.root, "type")
        result = jobs.execute(plan, [0], view_options=ExplorerOptions(auto_apply=False))
        self.assertEqual(result.moved, 1)
        self.assertEqual((self.root/"NEF"/"same.NEF").stat().st_mtime_ns, before)
        self.views.assert_not_called()

    def test_file_added_after_preview_is_never_overwritten(self):
        original = self.photo("same.JPG", b"original")
        plan = jobs.build_plan(self.root, "type")
        existing = self.photo("JPG/same.JPG", b"new destination")
        result = self.run_plan(plan)
        self.assertEqual((result.moved, result.skipped), (0, 1))
        self.assertEqual(original.read_bytes(), b"original")
        self.assertEqual(existing.read_bytes(), b"new destination")

    def test_changed_source_is_skipped(self):
        source = self.photo("same.NEF")
        plan = jobs.build_plan(self.root, "type")
        source.write_bytes(b"edited after preview")
        result = self.run_plan(plan)
        self.assertEqual((result.moved, result.skipped), (0, 1))
        self.assertTrue(source.exists())

    def test_nef_uses_mtime_and_preserves_nanoseconds(self):
        source = self.photo("20200101_010101.NEF")
        ns = int(datetime(2026, 9, 25, 12, 34, 56).timestamp()) * 10**9 + 123456700
        os.utime(source, ns=(ns, ns))
        before = source.stat().st_mtime_ns
        plan = jobs.build_plan(self.root, "date")
        destination = self.root / "2026-09-25" / source.name
        self.assertEqual(plan.items[0].destination, destination)
        result = self.run_plan(plan)
        self.assertEqual((result.moved, result.nef_preserved, result.dates_set), (1, 1, 0))
        self.assertEqual(destination.stat().st_mtime_ns, before)
        self.views.assert_called_once_with([destination], dry_run=False, options=None)

    def test_jpg_uses_exif_and_sets_mtime(self):
        from PIL import Image
        source = self.root / "20200101_010101.JPG"
        exif = Image.Exif()
        exif[36867] = "2026:05:29 16:55:29"
        Image.new("RGB", (16, 16), "white").save(source, exif=exif)
        plan = jobs.build_plan(self.root, "date")
        expected = datetime(2026, 5, 29, 16, 55, 29)
        self.assertEqual(plan.items[0].date, expected)
        result = self.run_plan(plan)
        destination = self.root / "2026-05-29" / source.name
        self.assertEqual(destination.stat().st_mtime, expected.timestamp())
        self.assertEqual((result.moved, result.dates_set), (1, 1))

    def test_video_filename_date(self):
        source = self.photo("20260926_154321.MOV")
        plan = jobs.build_plan(self.root, "date")
        self.assertEqual(plan.items[0].destination, self.root / "2026-09-26" / source.name)
        self.assertEqual(plan.items[0].date, datetime(2026, 9, 26, 15, 43, 21))

    def test_same_name_from_two_folders_is_preserved(self):
        self.photo("a/20260925_123456.JPG", b"first photo")
        self.photo("b/20260925_123456.JPG", b"second photo")
        plan = jobs.build_plan(self.root, "date")
        self.assertEqual(len({item.destination for item in plan.items}), 2)
        result = self.run_plan(plan)
        self.assertEqual((result.moved, result.failed), (2, 0))
        contents = {p.read_bytes() for p in (self.root / "2026-09-25").iterdir()}
        self.assertEqual(contents, {b"first photo", b"second photo"})

    def test_date_unknown_is_not_selectable(self):
        path = self.photo("unknown.JPG")
        plan = jobs.build_plan(self.root, "date")
        self.assertFalse(plan.items[0].eligible)
        self.assertTrue(path.exists())

    def test_no_recursive_option(self):
        self.photo("top.NEF")
        self.photo("nested/inside.NEF")
        plan = jobs.build_plan(self.root, "date", recursive=False)
        self.assertEqual([item.source.name for item in plan.items], ["top.NEF"])

    def test_date_folder_does_not_nest_again(self):
        folder = self.root / "2026-09-25"
        path = self.photo("2026-09-25/same.NEF")
        stamp = datetime(2026, 9, 25).timestamp()
        os.utime(path, (stamp, stamp))
        plan = jobs.build_plan(folder, "date")
        self.assertEqual(plan.items[0].destination, path)
        self.assertEqual(plan.base, self.root)

    def test_invalid_selection_makes_no_change(self):
        source = self.photo("same.JPG")
        plan = jobs.build_plan(self.root, "type")
        with self.assertRaises(ValueError):
            jobs.execute(plan, [0, 0])
        self.assertTrue(source.exists())


if __name__ == "__main__":
    unittest.main()
