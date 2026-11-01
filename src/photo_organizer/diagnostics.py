"""패키지 검증 전용 진입점. 지정한 임시 보고서 외에 기록을 남기지 않습니다."""
from __future__ import annotations

import argparse
import ctypes as ct
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
from photo_organizer.paths import artifact_path, configure_development


def verify():
    from PIL import Image
    import tkinter as tk
    from photo_organizer.core import jobs as jobs
    from photo_organizer.ui import organizer as ui
    from photo_organizer.windows.folder_views import ExplorerOptions
    from photo_organizer.ui.common import switch_tool
    from photo_organizer.version import VERSION

    results = {"version": VERSION, "frozen": bool(getattr(sys, "frozen", False)), "executable": sys.executable}
    if getattr(sys, "frozen", False):
        kernel = ct.WinDLL("kernel32")
        kernel.GetModuleHandleW.argtypes = [ct.c_wchar_p]
        kernel.GetModuleHandleW.restype = ct.c_void_p
        kernel.GetModuleFileNameW.argtypes = [ct.c_void_p, ct.c_wchar_p, ct.c_uint]
        path = ct.create_unicode_buffer(32768)
        assert kernel.GetModuleFileNameW(kernel.GetModuleHandleW("python312.dll"), path, len(path))
        results["python_runtime"] = path.value
        assert Path(path.value).parent == Path(sys.executable).parent / "_internal"
    with tempfile.TemporaryDirectory(prefix="PhotoOrganizer-verify-") as temporary:
        base = Path(temporary)
        date = base / "date"
        date.mkdir()
        raw = date / "DSC.NEF"
        raw.write_bytes(b"packaged raw fixture")
        stamp = int(datetime(2026, 9, 25, 12, 34).timestamp()) * 10**9 + 123456700
        os.utime(raw, ns=(stamp, stamp))
        original_stamp = raw.stat().st_mtime_ns
        jpg = date / "photo.JPG"
        image = Image.new("RGB", (12, 12), "white")
        exif = image.getexif()
        exif[36867] = "2026:09:26 13:14:15"
        image.save(jpg, exif=exif)
        plan = jobs.build_plan(date, "date", True)
        assert len(plan.items) == 2 and all(item.eligible for item in plan.items)
        result = jobs.execute(plan, [0, 1], view_options=ExplorerOptions(auto_apply=False))
        assert result.moved == 2 and not result.failed
        assert (date / "2026-09-25" / "DSC.NEF").stat().st_mtime_ns == original_stamp
        assert (date / "2026-09-26" / "photo.JPG").is_file()
        results["date_and_exif"] = True
        results["nef_timestamp_preserved"] = True

        types = base / "types"
        types.mkdir()
        for name in ("photo.JPG", "raw.NEF", "video.MOV", "keep.txt"):
            (types / name).write_bytes(b"packaged type fixture")
        plan = jobs.build_plan(types, "type", False)
        selected = [index for index, item in enumerate(plan.items) if item.eligible]
        result = jobs.execute(plan, selected)
        assert result.moved == 3 and not result.failed
        assert all((types / extension / name).is_file() for name, extension in (("photo.JPG", "JPG"), ("raw.NEF", "NEF"), ("video.MOV", "MOV")))
        assert (types / "keep.txt").is_file()
        results["file_classification"] = True
        applied, failed = jobs.apply_views(types, ExplorerOptions(), mode="type")
        assert set(applied) == {types/"JPG", types/"NEF", types/"MOV"} and not failed
        results["file_classification_views"] = True

        views = base / "views"
        views.mkdir()
        applied, failed = jobs.apply_views(views, ExplorerOptions(general_view="목록", general_ascending=False))
        assert applied and not failed
        results["native_explorer_settings"] = True

        ui.enable_dpi_awareness()
        root = tk.Tk()
        root.withdraw()
        errors = []
        root.report_callback_exception = lambda *error: errors.append(str(error))
        app = ui.OrganizerApp(root)
        root.update_idletasks()
        try:
            results["font_regular"] = root._photo_fonts["body"].actual("family")
            results["font_medium"] = root._photo_fonts["control"].actual("family")
            assert results["font_regular"] == "Photo Organizer UI"
            assert results["font_medium"] == "Photo Organizer UI Medium"
            assert root._photo_fonts["title"].actual("weight") == "bold"
            assert app.run_button.instate(["disabled"])
            assert not app.folder.get()
            fixture = base / "gui"
            fixture.mkdir()
            photo = fixture / "orphan.NEF"
            photo.write_bytes(b"packaged gui fixture")
            before = photo.read_bytes(), photo.stat().st_mtime_ns
            app.folder.set(str(fixture))
            for tool in ("type", "pair", "date"):
                app = switch_tool(root._photo_current_app, tool)
                assert app is not None
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    root.update()
                    if not app.busy and (getattr(app, "plan", None) is not None or getattr(app, "scan", None) is not None):
                        break
                    time.sleep(.01)
                else:
                    raise RuntimeError(f"GUI scan timed out: {tool}")
                assert app.checked
                assert Path(app.folder.get()) == fixture
                if tool == "type":
                    assert app.view_button is not None
                if tool == "pair":
                    assert app.scan.candidates[0].path == photo
                    assert app.kind == "both"
                    assert not hasattr(app, "mode_box")
            assert before == (photo.read_bytes(), photo.stat().st_mtime_ns)
            assert not errors, errors
            results["three_tool_navigation"] = True
            results["raw_jpg_preview"] = True
            results["both_formats_ui"] = True

            from photo_organizer.core.pairs import scan_folder, make_guard
            pair_root = base / "parent-copy"
            pair_root.mkdir()
            parent_copy = pair_root / "DSC_3710.JPG"
            parent_copy.write_bytes(b"edited jpg fixture")
            initial = scan_folder(pair_root, "jpg")
            assert len(initial.candidates) == 1
            dated_raw = pair_root / "RAW" / "2026-09-26" / "DSC_3710.NEF"
            dated_raw.parent.mkdir(parents=True)
            dated_raw.write_bytes(b"raw counterpart fixture")
            protected = scan_folder(pair_root, "jpg")
            assert not protected.candidates
            assert [p.path for p in protected.protected] == [parent_copy]
            try:
                make_guard(initial.candidates[0], initial)()
            except ValueError as error:
                assert "짝 파일" in str(error)
            else:
                raise AssertionError("parent JPG copy was not protected")
            assert parent_copy.read_bytes() == b"edited jpg fixture"
            results["parent_copy_pair_protection"] = True

            nested = base / "nested-formats"
            nested_raw = nested / "RAW" / "NEF" / "2026-09-26" / "DSC_3710.NEF"
            nested_jpg = nested / "JPG" / "2026-09-26" / "DSC_3710.JPG"
            for fixture_file in (nested_raw, nested_jpg):
                fixture_file.parent.mkdir(parents=True, exist_ok=True)
                fixture_file.write_bytes(b"nested format pair fixture")
            assert not scan_folder(nested).candidates
            from photo_organizer.ui.pairs import common_folder
            assert common_folder(nested_raw.parent)[0] == nested
            results["nested_format_pair_detection"] = True
            results["format_subfolder_selection"] = True
        finally:
            current = root._photo_current_app
            current.busy = False
            current.close()
        assert not list(base.rglob("*.csv"))
        results["no_record_files"] = True
    results["passed"] = True
    return results


def main(arguments):
    parser = argparse.ArgumentParser()
    configure_development()
    parser.add_argument("--report", type=Path, default=artifact_path("reports", "package.json"))
    args = parser.parse_args(arguments)
    reports = artifact_path("reports").resolve()
    args.report = args.report.resolve()
    if not args.report.is_relative_to(reports):
        parser.error("검증 보고서는 .work/reports 안에 저장하세요.")
    try:
        report = verify()
        code = 0
    except Exception:
        report = {"passed": False, "error": traceback.format_exc()}
        code = 1
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return code
