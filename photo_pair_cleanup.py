#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""짝이 없는 RAW/JPG를 검토한 뒤 선택한 파일만 휴지통으로 보냅니다.

기본: RAW와 JPG 양쪽에서 짝 없는 파일 찾기. --dry-run은 사진을 변경하지 않습니다.
추가 패키지는 필요하지 않습니다. photo_recycle_bin.py와 함께 보관하세요.
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from photo_recycle_bin import RecycleBin


RAW_EXTENSIONS = frozenset({
    ".nef", ".nrw", ".arw", ".srf", ".sr2", ".cr2", ".cr3", ".crw",
    ".dng", ".raf", ".rw2", ".rwl", ".orf", ".ori", ".pef", ".ptx",
    ".srw", ".raw", ".3fr", ".fff", ".iiq", ".kdc", ".mos", ".mrw",
    ".x3f", ".erf", ".mef", ".mdc", ".bay", ".cap", ".eip",
})
JPG_EXTENSIONS = frozenset({".jpg", ".jpeg", ".jpe"})
RAW_DIR_NAMES = frozenset({"raw", *(ext[1:] for ext in RAW_EXTENSIONS)})
JPG_DIR_NAMES = frozenset({"jpg", "jpeg", "jpe"})
FORMAT_DIR_NAMES = RAW_DIR_NAMES | JPG_DIR_NAMES
IGNORED_DIR_NAMES = frozenset({"$recycle.bin", "system volume information", ".git",
    "node_modules", "__pycache__"})
KIND_NAMES = {"raw": "JPG가 없는 RAW", "jpg": "RAW가 없는 JPG", "both": "양쪽 모두"}


def key(path: Path) -> str:
    return str(path).casefold()


def file_kind(path: Path) -> str | None:
    extension = path.suffix.lower()
    if extension in RAW_EXTENSIONS:
        return "raw"
    if extension in JPG_EXTENSIONS:
        return "jpg"
    return None


def is_reparse(info: os.stat_result) -> bool:
    return bool(getattr(info, "st_file_attributes", 0) & 0x400) or stat.S_ISLNK(info.st_mode)


def signature(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def logical_folder(directory: Path, root: Path) -> Path:
    """같은 폴더와 RAW/JPG 분리 폴더를 연결하되 날짜/행사 경로는 유지합니다."""
    relative = directory.relative_to(root)
    # 형식 폴더가 RAW/NEF처럼 중첩돼도 날짜/행사 이름은 유지합니다.
    parts = [part for part in relative.parts if part.casefold() not in FORMAT_DIR_NAMES]
    return root.joinpath(*parts)


def comparison_root(path: Path) -> Path:
    """형식별 폴더나 그 하위 날짜 폴더를 선택하면 공통 상위 폴더를 찾습니다."""
    target = path
    for ancestor in [path, *path.parents]:
        if ancestor.name.casefold() in FORMAT_DIR_NAMES:
            target = ancestor.parent
    return target


def related_scopes(first: str, second: str) -> bool:
    """상위에 남긴 사본은 보호하되 서로 다른 날짜/행사끼리는 연결하지 않습니다."""
    return (first == second or first.startswith(second + os.sep)
            or second.startswith(first + os.sep))


def photo_directories(root: Path, related_to: str | None = None):
    """검색과 휴지통 직전 검증에서 같은 폴더 비교 범위를 사용합니다."""
    def fail(error):
        raise OSError(f"폴더를 끝까지 읽지 못해 작업을 중단합니다: {error}")

    for folder, subfolders, names in os.walk(root, followlinks=False, onerror=fail):
        directory = Path(folder)
        if is_reparse(directory.lstat()):
            raise ValueError(f"연결된 폴더가 있어 비교를 중단합니다: {directory}")
        scope = key(logical_folder(directory, root))
        if related_to is not None and not (related_scopes(scope, related_to)
                or related_scopes(key(directory), related_to)):
            subfolders[:] = []
            continue
        kept = []
        for name in subfolders:
            child = directory / name
            if name.casefold() in IGNORED_DIR_NAMES:
                continue
            if related_to is not None and not (related_scopes(key(logical_folder(child, root)), related_to)
                    or related_scopes(key(child), related_to)):
                continue
            if is_reparse(child.lstat()):
                raise ValueError(f"연결된 폴더가 있어 비교를 중단합니다: {child}")
            kept.append(name)
        subfolders[:] = sorted(kept, key=str.casefold)
        if related_to is None or related_scopes(scope, related_to):
            yield directory, scope, names


@dataclass(frozen=True)
class Photo:
    path: Path
    kind: str
    scope: str
    identity: tuple[int, int, int, int, int]


@dataclass
class Scan:
    root: Path
    photos: list[Photo]
    candidates: list[Photo]
    directories: dict[str, list[Path]]
    pairs: int
    protected: list[Photo] = field(default_factory=list)


def validate_root(path: Path) -> Path:
    path = path.expanduser().absolute()
    # resolve()로 링크를 따라가기 전에 구성 경로를 확인합니다.
    for component in [*reversed(path.parents), path]:
        if is_reparse(component.lstat()):
            raise ValueError(f"연결된 폴더는 사용할 수 없습니다: {component}")
    root = path.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("사진 파일이 들어 있는 폴더를 선택하세요.")
    if root == Path(root.anchor):
        raise ValueError("드라이브 전체 대신 정리할 행사/날짜 폴더를 선택하세요.")
    # 반대 형식이 상위 폴더에 섞여 있는 경우도 한쪽만 검사하지 않도록 합니다.
    common = comparison_root(root)
    if common != root:
        raise ValueError(f"RAW와 JPG를 함께 비교해야 합니다. 다음 상위 폴더를 선택하세요:\n{common}")
    return root


def scan_folder(target: Path, kind: str = "both") -> Scan:
    root = validate_root(target)
    photos = []
    directories = defaultdict(list)
    groups = defaultdict(list)
    scopes_by_name = defaultdict(set)

    for directory, scope, names in photo_directories(root):
        directories[scope].append(directory)
        for name in sorted(names, key=str.casefold):
            path = directory / name
            category = file_kind(path)
            if not category:
                continue
            info = path.lstat()
            if is_reparse(info) or not stat.S_ISREG(info.st_mode):
                raise ValueError(f"일반 사진 파일이 아니므로 비교를 중단합니다: {path}")
            photo = Photo(path, category, scope, signature(info))
            photos.append(photo)
            groups[(scope, path.stem.casefold())].append(photo)
            scopes_by_name[(path.stem.casefold(), category)].add(scope)

    candidates = []
    protected = []
    pairs = 0
    for (scope, name), group in groups.items():
        kinds = {photo.kind for photo in group}
        if len(kinds) == 2:
            pairs += 1
        else:
            selected = [photo for photo in group if kind == "both" or photo.kind == kind]
            opposite = "jpg" if group[0].kind == "raw" else "raw"
            if any(related_scopes(scope, other) for other in scopes_by_name[(name, opposite)]):
                # 예: 행사/DSC_3710.JPG와 행사/RAW/2026-09-26/DSC_3710.NEF.
                # 정확한 날짜가 없는 상위 사본은 삭제 후보에서 보수적으로 제외합니다.
                protected.extend(selected)
            else:
                candidates.extend(selected)
    candidates.sort(key=lambda photo: key(photo.path))
    protected.sort(key=lambda photo: key(photo.path))
    return Scan(root, photos, candidates, dict(directories), pairs, protected)


def format_size(size: int) -> str:
    value = float(size)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return str(size)


def show_scan(scan: Scan, limit: int = 60) -> None:
    raw_count = sum(photo.kind == "raw" for photo in scan.photos)
    print(f"\n대상: {scan.root}")
    print(f"RAW {raw_count:,}개 / JPG {len(scan.photos) - raw_count:,}개 / 정상 쌍 {scan.pairs:,}개")
    if scan.protected:
        print(f"상위·하위 폴더에 같은 이름의 반대 형식이 있어 보존: {len(scan.protected):,}개")
    print(f"정리 후보: {len(scan.candidates):,}개 ({format_size(sum(p.identity[2] for p in scan.candidates))})")
    print()
    for number, photo in enumerate(scan.candidates[:limit], 1):
        print(f"{number:>5}. [{photo.kind.upper()}] {photo.path.relative_to(scan.root)}  ({format_size(photo.identity[2])})")
    if len(scan.candidates) > limit:
        print(f"... 나머지 {len(scan.candidates) - limit:,}개는 L을 눌러 전체 목록에서 확인하세요.")


def parse_selection(value: str, count: int) -> list[int]:
    value = value.strip()
    if value.casefold() == "a":
        return list(range(count))
    if not value or value.casefold() == "q":
        return []
    selected = set()
    for part in value.replace(" ", ",").split(","):
        if not part:
            continue
        ends = part.split("-")
        if len(ends) > 2 or not all(end.isascii() and end.isdecimal() for end in ends):
            raise ValueError("번호는 1,3,5-8 형식으로 입력하세요.")
        first, last = int(ends[0]), int(ends[-1])
        if first < 1 or last < first or last > count:
            raise ValueError(f"1~{count} 범위의 번호를 입력하세요.")
        selected.update(range(first - 1, last))
    return sorted(selected)


def make_guard(photo: Photo, scan: Scan):
    def guard():
        # 파일 내용 대신 파일 ID/크기/시각을 다시 확인합니다.
        if photo.path.resolve(strict=True) != photo.path or not photo.path.is_relative_to(scan.root):
            raise ValueError("대상 파일의 경로가 바뀌었습니다.")
        for component in [photo.path, *photo.path.parents]:
            if is_reparse(component.lstat()):
                raise ValueError("대상 경로에 연결된 파일/폴더가 생겼습니다.")
            if component == scan.root:
                break
        info = photo.path.lstat()
        if not stat.S_ISREG(info.st_mode) or signature(info) != photo.identity:
            raise ValueError("검색 후 파일이 변경되어 건너뜁니다.")
        # 새 날짜 폴더나 상위 사본이 생긴 경우도 검색과 동일한 기준으로 보호합니다.
        for directory, scope, names in photo_directories(scan.root, related_to=photo.scope):
            for name in names:
                other = directory / name
                other_kind = file_kind(other)
                if other_kind and other_kind != photo.kind and other.stem.casefold() == photo.path.stem.casefold():
                    raise ValueError("짝 파일이 생겨 건너뜁니다.")
    return guard


def recycle_selected(scan: Scan, selected: list[int], kind: str,
                     messages: list[str] | None = None) -> tuple[int, int]:
    # 재검색과 개별 파일 검증은 유지하고, 결과는 화면에만 표시합니다.
    if len(set(selected)) != len(selected) or any(i < 0 or i >= len(scan.candidates) for i in selected):
        raise ValueError("정리할 파일 선택을 다시 확인하세요.")
    fresh = scan_folder(scan.root, kind)
    current = {key(photo.path): photo for photo in fresh.candidates}
    completed = skipped = 0
    with RecycleBin() as recycle_bin:
        for number in selected:
            photo = scan.candidates[number]
            now = current.get(key(photo.path))
            result, message = "건너뜀", "검색 후 짝 파일이 생기거나 원본이 변경되었습니다."
            stop = False
            if now == photo:
                try:
                    recycle_bin.recycle(photo.path, make_guard(photo, fresh))
                    result, message = "휴지통 이동", ""
                    completed += 1
                except Exception as error:
                    result, message, stop = "중단", str(error), True
            if result != "휴지통 이동":
                skipped += 1
                if messages is not None:
                    messages.append(f"{photo.path.name}: {message}")
            print(f"[{result}] {photo.path.relative_to(scan.root)} {message}")
            if stop:
                print("오류가 발생해 나머지 작업을 중단했습니다.")
                break
    print(f"\n휴지통 이동 {completed:,}개 / 건너뜀·오류 {skipped:,}개")
    if remaining_count := len(selected) - completed - skipped:
        print(f"미실행 {remaining_count:,}개")
    return completed, skipped


def review(scan: Scan, kind: str) -> None:
    if not scan.candidates:
        print("정리할 후보가 없습니다.")
        return
    print("\n원래 RAW 또는 JPG만 촬영한 사진도 후보에 포함됩니다. 목록을 확인하세요.")
    print("번호 입력: 1,3,5-8 / A: 전체 선택 / L: 전체 목록 / Enter: 취소")
    while True:
        answer = input("정리할 파일> ").strip()
        if answer.casefold() == "l":
            show_scan(scan, len(scan.candidates))
            continue
        try:
            selected = parse_selection(answer, len(scan.candidates))
        except ValueError as error:
            print(error)
            continue
        break
    if not selected:
        print("취소했습니다. 사진을 변경하지 않았습니다.")
        return
    total_size = sum(scan.candidates[index].identity[2] for index in selected)
    print(f"\n선택한 {len(selected):,}개 ({format_size(total_size)})를 휴지통으로 보냅니다.")
    print("확인하려면 '휴지통'을 정확히 입력하세요. 다른 입력은 취소합니다.")
    if input("최종 확인> ").strip() != "휴지통":
        print("취소했습니다. 사진을 변경하지 않았습니다.")
        return
    recycle_selected(scan, selected, kind)


def main() -> int:
    parser = argparse.ArgumentParser(description="짝이 없는 RAW/JPG를 찾아 검토 후 휴지통으로 보냅니다.")
    parser.add_argument("folder", nargs="?", help="RAW와 JPG가 함께 들어 있는 상위 폴더")
    parser.add_argument("--kind", choices=["raw", "jpg", "both"], default="both", help="후보 종류 (기본 양쪽 모두)")
    parser.add_argument("--dry-run", action="store_true", help="후보 목록만 표시하고 종료합니다. 사진 변경 없음")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    print("RAW/JPG 짝 없는 파일 정리")
    print("같은 폴더 또는 RAW·JPG 분리 폴더의 이름을 비교합니다. 하위 날짜 폴더도 포함합니다.")
    folder = args.folder
    if args.dry_run and not folder:
        parser.error("--dry-run에는 비교할 폴더를 지정하세요.")
    while True:
        if not folder:
            print("\nRAW와 JPG가 함께 있는 폴더를 끌어 놓거나 경로를 입력하세요.")
            folder = input("폴더 [Enter: 종료]> ").strip().strip('"')
            if not folder or folder.casefold() == "q":
                return 0
        try:
            kind = args.kind
            print(f"\n검색 중... ({KIND_NAMES[kind]})")
            scan = scan_folder(Path(folder), kind)
            show_scan(scan)
            if args.dry_run:
                print("\n미리보기 완료. 사진을 변경하지 않았습니다.")
                return 0
            review(scan, kind)
        except (OSError, ValueError) as error:
            print(f"\n[오류] {error}")
            if args.dry_run:
                return 1
        folder = None


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (EOFError, KeyboardInterrupt):
        print("\n종료합니다.")
