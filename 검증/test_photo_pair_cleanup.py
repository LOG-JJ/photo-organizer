"""임시 파일만 사용하는 짝 검색 및 삭제 전 검증 회귀 테스트."""
import contextlib
import ctypes as ct
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import photo_pair_cleanup as app
from photo_recycle_bin import RecycleSink


class PairCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="photo_pair_test_")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "사진 행사 & 테스트"
        self.root.mkdir()

    def photo(self, relative, content=b"test photo"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def names(self, kind="raw"):
        return {p.path.relative_to(self.root).as_posix() for p in app.scan_folder(self.root, kind).candidates}

    def test_same_folder_case_and_multi_dot_names(self):
        self.photo("DSC_001.JPG")
        self.photo("dsc_001.nef")
        self.photo("version.2.CR3")
        self.photo("version.2.jPeG")
        self.photo("raw_only.ARW")
        self.photo("jpg_only.JPG")
        self.photo("movie.MOV")
        self.photo("note.xmp")
        self.assertEqual(self.names(), {"raw_only.ARW"})
        self.assertEqual(self.names("jpg"), {"jpg_only.JPG"})
        self.assertEqual(self.names("both"), {"raw_only.ARW", "jpg_only.JPG"})

    def test_default_search_includes_both_formats(self):
        self.photo("raw_only.NEF")
        self.photo("jpg_only.JPG")
        self.assertEqual({photo.kind for photo in app.scan_folder(self.root).candidates}, {"raw", "jpg"})

    def test_supported_raw_formats_pair_with_case_insensitive_jpeg_extensions(self):
        for index, extension in enumerate(sorted(app.RAW_EXTENSIONS)):
            self.photo(f"RAW/DSC_{index}.v2{extension.upper()}")
            jpeg_extension = sorted(app.JPG_EXTENSIONS)[index % len(app.JPG_EXTENSIONS)]
            self.photo(f"JPG/dsc_{index}.V2{jpeg_extension}")
        scan = app.scan_folder(self.root)
        self.assertFalse(scan.candidates)
        self.assertEqual(scan.pairs, len(app.RAW_EXTENSIONS))

    def test_split_folders_and_dates_stay_separate(self):
        self.photo("行事/RAW/2026-09-25/DSC_001.NEF")
        self.photo("行事/JPG/2026-09-25/DSC_001.JPG")
        self.photo("行事/RAW/2026-09-26/DSC_001.NEF")
        self.photo("行事/JPG/2026-09-26/DSC_002.JPG")
        self.photo("別行事/NEF/DSC_001.NEF")
        self.photo("別行事/JPEG/DSC_001.JPEG")
        self.assertEqual(self.names(), {"行事/RAW/2026-09-26/DSC_001.NEF"})
        self.assertEqual(self.names("jpg"), {"行事/JPG/2026-09-26/DSC_002.JPG"})

    def test_same_number_in_other_event_does_not_pair(self):
        self.photo("first/DSC_001.NEF")
        self.photo("second/DSC_001.JPG")
        self.assertEqual(len(self.names("both")), 2)

    def test_mixed_parent_and_format_child(self):
        self.photo("DSC_001.JPG")
        self.photo("RAW/DSC_001.NEF")
        self.assertEqual(self.names(), set())

    def test_nested_format_folders_do_not_hide_normal_pairs(self):
        self.photo("RAW/NEF/2026-09-26/DSC_3710.NEF")
        self.photo("JPG/2026-09-26/DSC_3710.JPG")
        self.assertEqual(self.names("both"), set())

    def test_selecting_only_raw_folder_with_parent_jpg_is_rejected(self):
        self.photo("RAW/DSC_3710.NEF")
        self.photo("DSC_3710.JPG")
        with self.assertRaisesRegex(ValueError, "상위 폴더"):
            app.scan_folder(self.root / "RAW", "both")

    def test_parent_jpg_copy_is_not_orphan_when_dated_pair_exists(self):
        parent_copy = self.photo("DSC_3710.JPG", b"edited jpg")
        self.photo("JPG/2026-09-26/DSC_3710.JPG", b"camera jpg")
        self.photo("RAW/2026-09-26/DSC_3710.NEF")
        self.assertEqual(self.names("both"), set())
        scan = app.scan_folder(self.root, "jpg")
        self.assertEqual([photo.path for photo in scan.protected], [parent_copy])
        self.assertEqual(scan.pairs, 1)

    def test_parent_and_dated_counterparts_are_protected_in_both_directions(self):
        self.photo("first/DSC_3710.JPG")
        self.photo("first/RAW/2026-09-26/dsc_3710.nef")
        self.photo("second/DSC_3711.NEF")
        self.photo("second/JPEG/2026-09-27/DSC_3711.JPEG")
        self.assertEqual(self.names("both"), set())

    def test_parent_match_does_not_connect_other_events_or_sibling_dates(self):
        self.photo("first/DSC_001.NEF")
        self.photo("second/JPG/2026-09-26/DSC_001.JPG")
        self.photo("third/RAW/2026-09-26/DSC_002.NEF")
        self.photo("third/JPG/2026-09-27/DSC_002.JPG")
        self.assertEqual(len(self.names("both")), 4)

    def test_format_only_root_requires_common_parent(self):
        self.photo("RAW/date/DSC_001.NEF")
        self.photo("JPEG/date/DSC_001.JPG")
        with self.assertRaisesRegex(ValueError, "상위 폴더"):
            app.scan_folder(self.root / "RAW" / "date")

    def test_counterpart_added_after_preview_is_protected(self):
        path = self.photo("RAW/DSC_001.NEF")
        (self.root / "JPG").mkdir()
        scan = app.scan_folder(self.root)
        guard = app.make_guard(scan.candidates[0], scan)
        self.photo("JPG/DSC_001.JPG")
        with self.assertRaisesRegex(ValueError, "짝 파일"):
            guard()
        self.assertTrue(path.exists())

    def test_modified_file_is_protected(self):
        path = self.photo("DSC_001.NEF")
        scan = app.scan_folder(self.root)
        path.write_bytes(b"modified after scan")
        with self.assertRaisesRegex(ValueError, "변경"):
            app.make_guard(scan.candidates[0], scan)()

    def test_new_format_directory_after_preview_is_protected(self):
        self.photo("RAW/date/DSC_001.NEF")
        scan = app.scan_folder(self.root)
        self.photo("JPEG/date/DSC_001.JPG")
        with self.assertRaisesRegex(ValueError, "짝 파일"):
            app.make_guard(scan.candidates[0], scan)()

    def test_new_dated_counterpart_after_preview_is_protected_by_guard(self):
        photo = self.photo("DSC_3710.JPG")
        scan = app.scan_folder(self.root, "jpg")
        guard = app.make_guard(scan.candidates[0], scan)
        self.photo("RAW/2026-09-26/DSC_3710.NEF")
        with self.assertRaisesRegex(ValueError, "짝 파일"):
            guard()
        self.assertTrue(photo.exists())

    def test_new_parent_counterpart_after_preview_is_protected_by_guard(self):
        self.photo("RAW/2026-09-26/DSC_3710.NEF")
        scan = app.scan_folder(self.root)
        guard = app.make_guard(scan.candidates[0], scan)
        self.photo("DSC_3710.JPG")
        with self.assertRaisesRegex(ValueError, "짝 파일"):
            guard()

    def test_guard_checks_same_folder_with_nested_format_directories(self):
        self.photo("RAW/day/NEF/DSC_3710.NEF")
        scan = app.scan_folder(self.root)
        self.photo("RAW/day/NEF/DSC_3710.JPG")
        self.assertFalse(app.scan_folder(self.root).candidates)
        with self.assertRaisesRegex(ValueError, "짝 파일"):
            app.make_guard(scan.candidates[0], scan)()

    def test_guard_does_not_connect_new_file_in_sibling_date(self):
        self.photo("RAW/2026-09-26/DSC_3710.NEF")
        scan = app.scan_folder(self.root)
        self.photo("JPG/2026-09-27/DSC_3710.JPG")
        self.assertEqual(len(app.scan_folder(self.root, "raw").candidates), 1)
        app.make_guard(scan.candidates[0], scan)()

    def test_revalidation_never_recycles_new_dated_pair(self):
        photo = self.photo("DSC_3710.JPG")
        scan = app.scan_folder(self.root, "jpg")
        self.photo("RAW/2026-09-26/DSC_3710.NEF")
        with patch.object(app, "RecycleBin") as recycle, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.recycle_selected(scan, [0], "jpg"), (0, 1))
            recycle.return_value.__enter__.return_value.recycle.assert_not_called()
        self.assertTrue(photo.exists())

    def test_incomplete_walk_aborts(self):
        def broken_walk(root, **kwargs):
            kwargs["onerror"](PermissionError("blocked"))
            yield
        with patch.object(app.os, "walk", broken_walk):
            with self.assertRaisesRegex(OSError, "끝까지"):
                app.scan_folder(self.root)

    def test_preview_does_not_create_files_or_change_photos(self):
        path = self.photo("DSC_001.NEF")
        before = path.read_bytes(), path.stat().st_mtime_ns
        scan = app.scan_folder(self.root)
        with contextlib.redirect_stdout(io.StringIO()):
            app.show_scan(scan)
        self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))
        self.assertEqual(list(self.root.iterdir()), [path])
        self.assertFalse(hasattr(app, "save_report"))

    def test_selection_parsing(self):
        self.assertEqual(app.parse_selection("1,3-5 3", 8), [0, 2, 3, 4])
        self.assertEqual(app.parse_selection("A", 3), [0, 1, 2])
        self.assertEqual(app.parse_selection("", 3), [])
        for value in ["0", "-1", "5-3", "9", "1-999999999", "1.5", "1--2", "one"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                app.parse_selection(value, 8)

    def test_cancel_never_calls_recycle(self):
        self.photo("DSC_001.NEF")
        scan = app.scan_folder(self.root)
        for answers in [[""], ["A", "wrong confirmation"]]:
            with patch("builtins.input", side_effect=answers), patch.object(app, "recycle_selected") as recycle:
                with contextlib.redirect_stdout(io.StringIO()):
                    app.review(scan, "raw")
                recycle.assert_not_called()

    def test_revalidation_excludes_new_pairs(self):
        path = self.photo("DSC_001.NEF")
        scan = app.scan_folder(self.root)
        self.photo("DSC_001.JPG")
        with patch.object(app, "RecycleBin") as recycle:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(app.recycle_selected(scan, [0], "raw"), (0, 1))
            recycle.return_value.__enter__.return_value.recycle.assert_not_called()
        self.assertTrue(path.exists())

    def test_recycle_failure_stops_remaining_files(self):
        first = self.photo("DSC_001.NEF")
        second = self.photo("DSC_002.NEF")
        scan = app.scan_folder(self.root)
        with patch.object(app, "RecycleBin") as recycle:
            recycle.return_value.__enter__.return_value.recycle.side_effect = OSError("cannot recycle")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(app.recycle_selected(scan, [0, 1], "raw"), (0, 1))
            self.assertEqual(recycle.return_value.__enter__.return_value.recycle.call_count, 1)
        self.assertTrue(first.exists() and second.exists())

    @unittest.skipUnless(os.name == "nt", "Windows COM callback")
    def test_sink_refuses_permanent_delete(self):
        sink = RecycleSink(lambda: None)
        self.assertLess(sink.callbacks[11](sink.pointer, 0, None), 0)
        self.assertIn("영구 삭제", sink.error)

    @unittest.skipUnless(os.name == "nt", "Windows COM callback")
    def test_sink_refuses_failed_guard(self):
        def guard():
            raise ValueError("photo changed")
        sink = RecycleSink(guard)
        self.assertLess(sink.callbacks[11](sink.pointer, 0x80, None), 0)
        self.assertEqual(sink.error, "photo changed")


if __name__ == "__main__":
    unittest.main()
