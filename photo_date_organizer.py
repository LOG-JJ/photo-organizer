#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
사진/동영상 파일을 촬영 날짜별 폴더로 정리하고,
파일의 수정한 날짜를 촬영 날짜와 같게 맞춥니다.
NEF는 기존 수정한 날짜로 분류하고 그 시각을 그대로 유지합니다.

사용 예:
  python photo_date_organizer.py "D:\\사진\\새로가져온사진"
  python photo_date_organizer.py "D:\\사진\\새로가져온사진" --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from photo_folder_views import (
    FolderViewStore,
    SORT_DATE_MODIFIED,
    SORT_DATE_TAKEN,
    SORT_NAME,
    ExplorerOptions,
    SORT_KEYS,
)


try:
    from PIL import Image
except Exception:  # pragma: no cover - Pillow가 없는 PC에서도 실행되게 둡니다.
    Image = None


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".jpe",
    ".tif",
    ".tiff",
    ".png",
    ".webp",
    ".heic",
    ".heif",
    ".nef",
}

VIDEO_EXTENSIONS = {
    ".mov",
    ".mp4",
    ".m4v",
    ".3gp",
    ".3g2",
    ".avi",
}

MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
DATE_FOLDER_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SAFE_YEAR_MIN = 1990
SAFE_YEAR_MAX = 2100


@dataclass(frozen=True)
class MediaPlan:
    source: Path
    destination: Path | None
    taken_at: datetime | None
    reason: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="사진/동영상을 날짜별로 정리합니다. NEF는 수정한 날짜, 나머지는 촬영 날짜를 사용합니다."
    )
    parser.add_argument(
        "targets",
        nargs="*",
        help="정리할 폴더 또는 파일.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제로 옮기지 않고 어떤 작업을 할지만 미리 봅니다.",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="하위 폴더까지 보지 않고 지정한 폴더 바로 안의 파일만 정리합니다.",
    )
    parser.add_argument(
        "--no-shell-metadata",
        action="store_true",
        help="윈도우 탐색기 메타데이터 조회를 끕니다. HEIC 일부는 날짜를 못 찾을 수 있습니다.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="확인 질문 없이 바로 실행합니다.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="작업 후 다음 폴더 경로를 입력받아 연속으로 정리합니다.",
    )
    return parser.parse_args()


def prompt_targets() -> list[Path]:
    print()
    print("정리할 폴더 경로를 입력하세요.")
    print("예: D:\\사진\\새로가져온사진")
    print("그냥 엔터를 누르면 이 실행 파일이 있는 폴더를 대상으로 합니다.")
    raw = input("> ").strip().strip('"')
    if raw:
        return [Path(raw)]
    return [Path(__file__).resolve().parent]


def normalize_target(raw_target: str | Path) -> Path:
    target = Path(raw_target).expanduser()
    if not target.is_absolute():
        target = Path.cwd() / target
    return target.resolve()


def is_media_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS


def iter_media_files(target: Path, recursive: bool) -> Iterable[Path]:
    if target.is_file():
        if is_media_file(target):
            yield target
        return

    iterator = target.rglob("*") if recursive else target.glob("*")
    script_paths = {
        Path(__file__).resolve(),
        Path(__file__).with_suffix(".bat").resolve(),
    }
    for path in iterator:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in script_paths:
            continue
        if is_media_file(path):
            yield path


def parse_datetime_text(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    text = text.replace("\x00", " ")
    text = re.sub(r"\s+", " ", text).strip()

    # 윈도우 한글 메타데이터: 2025-08-23 오후 2:53
    match = re.search(
        r"(?<!\d)(19\d{2}|20\d{2})\D+(\d{1,2})\D+(\d{1,2})"
        r"\D+(오전|오후|AM|PM)\D*(\d{1,2})(?:[:시]\s*(\d{1,2}))?(?:[:분]\s*(\d{1,2}))?",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        year, month, day, meridiem, hour, minute, second = match.groups()
        return safe_datetime(year, month, day, hour, minute, second, meridiem)

    # EXIF 표준: 2025:08:23 16:55:29
    match = re.search(
        r"(?<!\d)(19\d{2}|20\d{2})[:./-](\d{1,2})[:./-](\d{1,2})"
        r"(?:[ T_]+(\d{1,2})[:._-](\d{1,2})(?:[:._-](\d{1,2}))?)?",
        text,
    )
    if match:
        year, month, day, hour, minute, second = match.groups()
        return safe_datetime(year, month, day, hour, minute, second)

    return None


def safe_datetime(
    year: object,
    month: object,
    day: object,
    hour: object = None,
    minute: object = None,
    second: object = None,
    meridiem: str | None = None,
) -> datetime | None:
    try:
        y = int(year)
        m = int(month)
        d = int(day)
        h = int(hour) if hour is not None else 0
        mi = int(minute) if minute is not None else 0
        s = int(second) if second is not None else 0
        if meridiem:
            meridiem = meridiem.upper()
            if meridiem in {"오후", "PM"} and h < 12:
                h += 12
            elif meridiem in {"오전", "AM"} and h == 12:
                h = 0
        if not (SAFE_YEAR_MIN <= y <= SAFE_YEAR_MAX):
            return None
        return datetime(y, m, d, h, mi, s)
    except Exception:
        return None


def datetime_from_filename(path: Path) -> datetime | None:
    name = path.stem
    patterns = [
        # 2024_03_03_15_57_IMG_3384, 2025-08-23 14.53.10
        r"(?<!\d)(19\d{2}|20\d{2})[-_. ](\d{1,2})[-_. ](\d{1,2})"
        r"(?:[-_. T](\d{1,2})[-_. ](\d{1,2})(?:[-_. ](\d{1,2}))?)?",
        # 20230117_125018000_iOS, 20230117-125018
        r"(?<!\d)(19\d{2}|20\d{2})(\d{2})(\d{2})"
        r"(?:[-_ ]?(\d{2})(\d{2})(\d{2})?)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, name)
        if not match:
            continue
        dt = safe_datetime(*match.groups())
        if dt:
            return dt
    return None


def datetime_from_exif(exif) -> datetime | None:
    # 원본 촬영 시각은 보통 최상위 IFD가 아니라 Exif 하위 IFD에 있습니다.
    try:
        capture_tags = exif.get_ifd(34665)
    except Exception:
        capture_tags = {}
    for tag in (36867, 36868, 306):  # DateTimeOriginal, DateTimeDigitized, DateTime
        dt = parse_datetime_text(capture_tags.get(tag)) or parse_datetime_text(exif.get(tag))
        if dt:
            return dt
    return None


def datetime_from_image_exif(path: Path) -> datetime | None:
    if Image is None or path.suffix.lower() not in IMAGE_EXTENSIONS or path.suffix.lower() == ".nef":
        return None
    try:
        with Image.open(path) as image:
            return datetime_from_exif(image.getexif())
    except Exception:
        return None


def iter_boxes(file_obj, end: int):
    while file_obj.tell() < end:
        start = file_obj.tell()
        header = file_obj.read(8)
        if len(header) < 8:
            return
        size, box_type = struct.unpack(">I4s", header)
        header_size = 8
        if size == 1:
            large_size = file_obj.read(8)
            if len(large_size) < 8:
                return
            size = struct.unpack(">Q", large_size)[0]
            header_size = 16
        elif size == 0:
            size = end - start
        if size < header_size:
            return
        try:
            box_name = box_type.decode("latin1")
        except Exception:
            box_name = ""
        yield start, size, header_size, box_name
        file_obj.seek(start + size)


def datetime_from_quicktime(path: Path) -> datetime | None:
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        return None
    try:
        with path.open("rb") as file_obj:
            file_obj.seek(0, os.SEEK_END)
            total_size = file_obj.tell()
            file_obj.seek(0)
            for start, size, header_size, box_name in iter_boxes(file_obj, total_size):
                if box_name != "moov":
                    continue
                moov_end = start + size
                file_obj.seek(start + header_size)
                for inner_start, inner_size, inner_header_size, inner_name in iter_boxes(
                    file_obj, moov_end
                ):
                    if inner_name == "mvhd":
                        file_obj.seek(inner_start + inner_header_size)
                        version_data = file_obj.read(1)
                        if not version_data:
                            return None
                        version = version_data[0]
                        file_obj.read(3)
                        if version == 1:
                            raw = file_obj.read(8)
                            if len(raw) < 8:
                                return None
                            created = struct.unpack(">Q", raw)[0]
                        else:
                            raw = file_obj.read(4)
                            if len(raw) < 4:
                                return None
                            created = struct.unpack(">I", raw)[0]
                        unix_seconds = created - 2082844800
                        if unix_seconds <= 0:
                            return None
                        dt = datetime.fromtimestamp(unix_seconds)
                        if SAFE_YEAR_MIN <= dt.year <= SAFE_YEAR_MAX:
                            return dt.replace(microsecond=0)
                        return None
                    file_obj.seek(inner_start + inner_size)
    except Exception:
        return None
    return None


def powershell_executable() -> str | None:
    for exe in ("powershell.exe", "pwsh.exe"):
        if shutil.which(exe):
            return exe
    return None


def shell_metadata_dates(paths: list[Path]) -> dict[Path, datetime]:
    if not paths or os.name != "nt":
        return {}

    exe = powershell_executable()
    if not exe:
        return {}

    payload_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", suffix=".json", delete=False
        ) as payload:
            json.dump([str(path) for path in paths], payload, ensure_ascii=False)
            payload_path = payload.name

        script = r"""
$ErrorActionPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$PayloadPath = $env:PHOTO_ORGANIZER_PAYLOAD
$paths = Get-Content -Raw -Encoding UTF8 -LiteralPath $PayloadPath | ConvertFrom-Json
$shell = New-Object -ComObject Shell.Application
$items = foreach ($p in $paths) {
  $file = Get-Item -LiteralPath $p -ErrorAction SilentlyContinue
  if ($null -eq $file) { continue }
  $folder = $shell.Namespace($file.DirectoryName)
  if ($null -eq $folder) { continue }
  $item = $folder.ParseName($file.Name)
  if ($null -eq $item) { continue }
  [PSCustomObject]@{
    Path = $file.FullName
    DateTaken = $folder.GetDetailsOf($item, 12)
    MediaCreated = $folder.GetDetailsOf($item, 209)
  }
}
$items | ConvertTo-Json -Depth 3 -Compress
"""
        env = os.environ.copy()
        env["PHOTO_ORGANIZER_PAYLOAD"] = payload_path
        completed = subprocess.run(
            [
                exe,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            return {}

        raw = json.loads(completed.stdout)
        if isinstance(raw, dict):
            raw = [raw]

        result: dict[Path, datetime] = {}
        for item in raw:
            item_path = normalize_target(item.get("Path", ""))
            dt = parse_datetime_text(item.get("DateTaken")) or parse_datetime_text(
                item.get("MediaCreated")
            )
            if dt:
                result[item_path] = dt
        return result
    except Exception:
        return {}
    finally:
        if payload_path:
            try:
                os.unlink(payload_path)
            except OSError:
                pass


def first_pass_datetime(path: Path) -> tuple[datetime | None, str]:
    if path.suffix.lower() == ".nef":
        try:
            return datetime.fromtimestamp(path.stat().st_mtime), "수정한 날짜"
        except (OSError, ValueError, OverflowError):
            return None, "수정한 날짜 읽기 실패"
    for label, reader in (
        ("EXIF", datetime_from_image_exif),
        ("QuickTime", datetime_from_quicktime),
        ("파일명", datetime_from_filename),
    ):
        dt = reader(path)
        if dt:
            return dt, label
    return None, "날짜 없음"


def unique_destination(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def build_plan(
    targets: list[Path],
    recursive: bool,
    use_shell_metadata: bool,
) -> list[MediaPlan]:
    media_files: list[Path] = []
    target_roots: dict[Path, Path] = {}

    for target in targets:
        target = normalize_target(target)
        if not target.exists():
            print(f"[건너뜀] 대상이 없습니다: {target}")
            continue
        root = target if target.is_dir() else target.parent
        print(f"[검색] {target}", flush=True)
        for media_file in iter_media_files(target, recursive=recursive):
            resolved = media_file.resolve()
            media_files.append(resolved)
            target_roots[resolved] = root

    plans: list[MediaPlan] = []
    unresolved: list[Path] = []
    first_pass: dict[Path, tuple[datetime | None, str]] = {}

    ordered_files = sorted(set(media_files), key=lambda item: str(item).lower())
    print(f"[검색 완료] 사진/동영상 {len(ordered_files):,}개. 분류 기준 날짜를 확인합니다.", flush=True)
    for index, path in enumerate(ordered_files, start=1):
        dt, reason = first_pass_datetime(path)
        first_pass[path] = (dt, reason)
        if dt is None and path.suffix.lower() != ".nef":
            unresolved.append(path)
        if index % 100 == 0 or index == len(ordered_files):
            print(f"[날짜 확인] {index:,}/{len(ordered_files):,}개", flush=True)

    shell_dates: dict[Path, datetime] = {}
    if use_shell_metadata and unresolved:
        print(f"[추가 조회] 날짜를 못 읽은 {len(unresolved):,}개를 Windows에서 확인합니다.", flush=True)
        for start in range(0, len(unresolved), 50):
            batch = unresolved[start:start + 50]
            shell_dates.update(shell_metadata_dates(batch))
            print(f"[Windows 날짜 확인] {start + len(batch):,}/{len(unresolved):,}개", flush=True)

    for path in ordered_files:
        dt, reason = first_pass[path]
        if dt is None and path in shell_dates:
            dt = shell_dates[path]
            reason = "윈도우 메타데이터"

        if dt is None:
            plans.append(MediaPlan(path, None, None, reason))
            continue

        root = target_roots[path]
        # 날짜 폴더 자체를 다시 정리해도 날짜 폴더가 중첩되지 않게 합니다.
        if DATE_FOLDER_RE.fullmatch(root.name):
            root = root.parent
        date_folder = root / dt.strftime("%Y-%m-%d")
        destination = date_folder / path.name

        try:
            if path.resolve() == destination.resolve():
                destination = path
            else:
                destination = unique_destination(destination)
        except OSError:
            destination = unique_destination(destination)

        plans.append(MediaPlan(path, destination, dt, reason))

    return plans


def confirm_if_needed(targets: list[Path], plans: list[MediaPlan], assume_yes: bool) -> bool:
    if assume_yes:
        return True

    total = len(plans)
    movable = sum(1 for plan in plans if plan.destination and plan.destination != plan.source)
    date_only = sum(1 for plan in plans if plan.destination == plan.source)
    skipped = sum(1 for plan in plans if plan.destination is None)

    print()
    print("작업 요약")
    print(f"- 대상: {', '.join(str(target) for target in targets)}")
    print(f"- 찾은 미디어 파일: {total}개")
    print(f"- 날짜 폴더로 이동: {movable}개")
    print(f"- 위치 유지: {date_only}개")
    print(f"- 날짜를 못 찾아 건너뜀: {skipped}개")

    if total == 0:
        print("정리할 사진/동영상 파일을 찾지 못했습니다.")
        return False

    print()
    answer = input("진행할까요? (Y/N) ").strip().lower()
    return answer in {"y", "yes", "예", "ㅇ"}


def set_modified_time(path: Path, taken_at: datetime, dry_run: bool) -> None:
    if dry_run:
        return
    timestamp = taken_at.timestamp()
    os.utime(path, (timestamp, timestamp))


def folder_sort_key(folder: Path, extensions=None):
    extensions = set(extensions or ())
    if folder.is_dir():
        extensions.update(path.suffix.lower() for path in folder.iterdir() if path.is_file())
    return SORT_DATE_MODIFIED if ".nef" in extensions or not extensions & IMAGE_EXTENSIONS else SORT_DATE_TAKEN


def folder_view_settings(media_paths: list[Path]) -> dict[Path, tuple[bool, tuple[str, int]]]:
    """이번에 정리한 날짜 폴더와 그 상위 폴더의 보기만 설정합니다."""
    date_folders: dict[Path, set[str]] = {}
    for path in media_paths:
        date_folders.setdefault(path.parent, set()).add(path.suffix.lower())

    settings: dict[Path, tuple[bool, tuple[str, int]]] = {}
    for folder, extensions in date_folders.items():
        sort_key = folder_sort_key(folder, extensions)
        settings[folder.parent] = (True, SORT_NAME)
        settings[folder] = (False, sort_key)
    return settings


def apply_folder_views(media_paths: list[Path], dry_run: bool, options: ExplorerOptions | None = None,
                       *, include_parent: bool = True) -> int:
    options = options or ExplorerOptions()
    if not options.auto_apply:
        return 0
    if not media_paths:
        return 0
    try:
        settings = folder_view_settings(media_paths)
        if not include_parent:
            settings = {folder: profile for folder, profile in settings.items() if not profile[0]}
    except OSError as exc:
        print(f"[보기 설정 실패] 폴더 내용을 확인할 수 없습니다: {exc}")
        return 1

    for folder, (details, sort_key) in sorted(settings.items(), key=lambda item: str(item[0]).lower()):
        view, selected_sort, ascending = options.profile(not details, sort_key)
        label = next((label for label, key in SORT_KEYS.items() if key == selected_sort), "날짜")
        print(f"[보기{' 미리보기' if dry_run else ''}] {folder}: {view}, {label} {'오름차순' if ascending else '내림차순'}")
    if dry_run:
        return 0

    failed = 0
    try:
        with FolderViewStore() as store:
            for folder, (details, sort_key) in settings.items():
                try:
                    view, selected_sort, ascending = options.profile(not details, sort_key)
                    store.apply(folder, view=view, sort_key=selected_sort, ascending=ascending)
                except Exception as exc:
                    failed += 1
                    print(f"[보기 설정 실패] {folder}: {exc}")
    except Exception as exc:
        print(f"[보기 설정 실패] {exc}")
        return len(settings)
    if not failed:
        print("- 탐색기 보기/정렬 설정 저장 완료 (이미 열려 있는 폴더는 닫았다가 다시 열어 주세요.)")
    return failed


def execute_plan(plans: list[MediaPlan], dry_run: bool) -> int:
    moved = 0
    touched = 0
    preserved = 0
    skipped = 0
    failed = 0
    organized_paths: list[Path] = []

    for plan in plans:
        if plan.destination is None or plan.taken_at is None:
            skipped += 1
            print(f"[건너뜀] 날짜 없음: {plan.source}")
            continue

        try:
            if not dry_run:
                plan.destination.parent.mkdir(parents=True, exist_ok=True)
            final_path = plan.destination
            if final_path != plan.source:
                print(
                    f"[이동] {plan.source.name} -> "
                    f"{final_path.parent.name}\\{final_path.name} ({plan.reason})"
                )
                if not dry_run:
                    shutil.move(str(plan.source), str(final_path))
                moved += 1
            else:
                print(f"[위치 유지] {plan.source} ({plan.reason})")

            if final_path.suffix.lower() == ".nef":
                # 분류에 사용한 원래 수정 시각을 나노초 단위까지 유지합니다.
                preserved += 1
            else:
                set_modified_time(final_path, plan.taken_at, dry_run=dry_run)
                touched += 1
            organized_paths.append(final_path)
        except Exception as exc:
            failed += 1
            print(f"[실패] {plan.source}: {exc}")

    print()
    view_failed = apply_folder_views(organized_paths, dry_run=dry_run)
    print()
    print("완료 요약")
    print(f"- 이동: {moved}개")
    print(f"- 수정한 날짜 맞춤: {touched}개")
    print(f"- NEF 수정한 날짜 유지: {preserved}개")
    print(f"- 건너뜀: {skipped}개")
    print(f"- 실패: {failed}개")
    print(f"- 보기/정렬 설정 실패: {view_failed}개 폴더")
    if dry_run:
        print("- 미리보기 모드라 실제 파일은 변경하지 않았습니다.")
    return 1 if failed or view_failed else 0


def organize_targets(args: argparse.Namespace, raw_targets: list[Path]) -> int:
    targets = [normalize_target(target) for target in raw_targets]

    plans = build_plan(
        targets=targets,
        recursive=not args.no_recursive,
        use_shell_metadata=not args.no_shell_metadata,
    )

    if not args.dry_run and not confirm_if_needed(targets, plans, assume_yes=args.yes):
        print("취소했습니다.")
        return 0

    return execute_plan(plans, dry_run=args.dry_run)


def main() -> int:
    args = parse_args()
    try:
        raw_targets = [Path(item.strip('"')) for item in args.targets] if args.targets else prompt_targets()
        while True:
            result = organize_targets(args, raw_targets)
            if not args.interactive:
                return result

            print()
            print("다음에 정리할 폴더 경로를 입력하거나 이 창으로 폴더를 끌어다 놓으세요.")
            print("종료하려면 그냥 엔터를 누르거나 Q를 입력하세요.")
            raw = input("> ").strip().strip('"')
            if not raw or raw.lower() in {"q", "quit", "exit", "종료"}:
                return 0
            raw_targets = [Path(raw)]
    except (EOFError, KeyboardInterrupt):
        print("\n종료합니다.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
