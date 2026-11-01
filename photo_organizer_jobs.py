"""날짜별 정리/확장자 분류의 미리보기와 실행. 사진은 명시적으로 실행해야 이동합니다."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import os
from pathlib import Path
import stat
from typing import Callable

import photo_date_organizer as dates
from photo_folder_views import ExplorerOptions, FolderViewStore, SORT_NAME

TYPE_FOLDERS = {".jpg": "JPG", ".nef": "NEF", ".mov": "MOV"}


def signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def is_link(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def check_ancestors(path: Path):
    for part in [*reversed(path.parents), path]:
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if is_link(info):
            raise ValueError(f"연결된 파일/폴더는 정리할 수 없습니다: {part}")


def validate_root(path: Path) -> Path:
    path = path.expanduser().absolute()
    check_ancestors(path)
    root = path.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("정리할 사진이 들어 있는 폴더를 선택하세요.")
    if root == Path(root.anchor):
        raise ValueError("드라이브 전체 대신 정리할 사진 폴더를 선택하세요.")
    return root


@dataclass(frozen=True)
class Item:
    source: Path
    destination: Path | None
    date: datetime | None
    reason: str
    identity: tuple

    @property
    def eligible(self):
        return self.destination is not None


@dataclass
class Plan:
    root: Path
    base: Path
    mode: str
    items: list[Item]


@dataclass
class Result:
    moved: int = 0
    dates_set: int = 0
    nef_preserved: int = 0
    skipped: int = 0
    failed: int = 0
    view_failed: int = 0
    rows: dict[int, tuple[str, str]] = field(default_factory=dict)


def unique_path(base: Path, reserved: set[Path]) -> Path:
    candidate, counter = base, 1
    while os.path.lexists(candidate) or candidate in reserved:
        candidate = base.with_name(f"{base.stem} ({counter}){base.suffix}")
        counter += 1
    return candidate


def collect(root: Path, recursive: bool, extensions: set[str]) -> list[Path]:
    result = []
    def fail(error):
        raise OSError(f"폴더를 끝까지 읽지 못했습니다: {error}")
    for folder, children, files in os.walk(root, followlinks=False, onerror=fail):
        directory = Path(folder)
        if recursive:
            for name in children:
                if is_link((directory / name).lstat()):
                    raise ValueError(f"연결된 폴더가 있습니다: {directory / name}")
        else:
            children[:] = []
        for name in files:
            path = directory / name
            if path.suffix.lower() not in extensions:
                continue
            info = path.lstat()
            if is_link(info) or not stat.S_ISREG(info.st_mode):
                raise ValueError(f"일반 파일이 아닙니다: {path}")
            result.append(path)
    return sorted(result, key=lambda path: str(path).casefold())


def build_plan(path: Path, mode: str, recursive: bool = True) -> Plan:
    if mode not in {"date", "type"}:
        raise ValueError("지원하지 않는 정리 방식입니다.")
    root = validate_root(path)
    extensions = dates.MEDIA_EXTENSIONS if mode == "date" else set(TYPE_FOLDERS)
    sources = collect(root, recursive if mode == "date" else False, extensions)
    identities = {source: signature(source.lstat()) for source in sources}
    items = []
    if mode == "type":
        for source in sources:
            destination = root / TYPE_FOLDERS[source.suffix.lower()] / source.name
            reason = f"{TYPE_FOLDERS[source.suffix.lower()]} 폴더로 이동"
            if os.path.lexists(destination):
                destination, reason = None, "같은 이름이 있어 건너뜀"
            items.append(Item(source, destination, None, reason, identities[source]))
        return Plan(root, root, mode, items)

    # 기존 촬영일 판독/NEF 기준을 그대로 사용합니다. 검증된 파일 목록만 전달합니다.
    raw_plans = dates.build_plan(sources, recursive=False, use_shell_metadata=True)
    base = root.parent if dates.DATE_FOLDER_RE.fullmatch(root.name) else root
    reserved = set()
    for original in raw_plans:
        source = original.source
        if source not in identities:
            raise ValueError("검색 중 파일 목록이 바뀌었습니다. 폴더를 다시 선택하세요.")
        destination = None
        reason = {"EXIF": "촬영 날짜", "QuickTime": "동영상 날짜",
                  "윈도우 메타데이터": "촬영/작성 날짜", "파일명": "파일명 날짜"}.get(
                      original.reason, original.reason)
        if original.taken_at is not None:
            desired = base / original.taken_at.strftime("%Y-%m-%d") / source.name
            destination = source if desired == source else unique_path(desired, reserved)
            reserved.add(destination)
            if destination.name != source.name:
                reason += " · 중복 이름 변경"
            if destination == source:
                reason += " · 날짜/보기 정리"
        else:
            reason = "날짜를 찾지 못해 건너뜀"
        items.append(Item(source, destination, original.taken_at, reason, identities[source]))
    return Plan(root, base, mode, items)


def check_item(plan: Plan, item: Item):
    if not item.destination:
        raise ValueError("이 파일은 정리 대상이 아닙니다.")
    check_ancestors(item.source)
    check_ancestors(item.destination.parent)
    if item.source.resolve(strict=True) != item.source or not item.source.is_relative_to(plan.root):
        raise ValueError("원본 파일의 경로가 바뀌었습니다.")
    if not item.destination.is_relative_to(plan.base):
        raise ValueError("정리할 위치가 선택한 폴더 범위를 벗어납니다.")
    if signature(item.source.lstat()) != item.identity:
        raise ValueError("검색 후 파일이 바뀌어 건너뜁니다.")
    if item.destination != item.source and os.path.lexists(item.destination):
        raise ValueError("같은 이름의 파일이 생겨 건너뜁니다.")


def execute(plan: Plan, selected: list[int],
            progress: Callable[[int, int, str], None] | None = None,
            view_options=None) -> Result:
    if len(set(selected)) != len(selected) or any(i < 0 or i >= len(plan.items) or not plan.items[i].eligible for i in selected):
        raise ValueError("정리할 파일 선택을 다시 확인하세요.")
    result = Result()
    organized = []
    for position, index in enumerate(selected, 1):
        item = plan.items[index]
        outcome, note = "완료", ""
        try:
            check_item(plan, item)
        except (OSError, ValueError) as error:
            outcome, note = "건너뜀", str(error)
            result.skipped += 1
        else:
            try:
                destination = item.destination
                destination.parent.mkdir(parents=True, exist_ok=True)
                check_item(plan, item)
                if destination != item.source:
                    # Windows의 rename은 기존 파일을 덮어쓰지 않습니다.
                    os.rename(item.source, destination)
                    result.moved += 1
                if plan.mode == "date":
                    if destination.suffix.lower() == ".nef":
                        result.nef_preserved += 1
                    else:
                        dates.set_modified_time(destination, item.date, dry_run=False)
                        result.dates_set += 1
                organized.append(destination)
            except Exception as error:
                outcome, note = "오류", str(error)
                result.failed += 1
        result.rows[index] = (outcome, note)
        if progress:
            progress(position, len(selected), item.source.name)
    if organized and (view_options is None or view_options.auto_apply):
        if progress:
            progress(len(selected), len(selected), "탐색기 보기와 정렬을 맞추고 있어요")
        result.view_failed = dates.apply_folder_views(organized, dry_run=False, options=view_options,
            **({"include_parent": False} if plan.mode == "type" else {}))
    return result


def apply_views(path: Path, options: ExplorerOptions, mode: str = "date"):
    """파일을 이동하지 않고 선택한 폴더와 정리 대상 폴더의 보기만 변경합니다."""
    if mode not in {"date", "type"}:
        raise ValueError("지원하지 않는 정리 방식입니다.")
    root = validate_root(path)
    folders = set() if mode == "type" else {root}
    classified = set()
    def fail(error):
        raise OSError(f"보기 설정 대상 폴더를 읽지 못했습니다: {error}")
    for directory, children, _ in os.walk(root, followlinks=False, onerror=fail):
        parent = Path(directory)
        if mode == "type":
            children[:] = [name for name in children if name.upper() in TYPE_FOLDERS.values()]
        for name in children:
            child = parent / name
            if is_link(child.lstat()):
                raise ValueError(f"연결된 폴더가 있어 설정을 중단합니다: {child}")
            if mode == "type":
                folders.add(child)
                classified.add(child)
            elif dates.DATE_FOLDER_RE.fullmatch(name):
                folders.update((child, parent))
        if mode == "type":
            children[:] = []
    planned = []
    for folder in sorted(folders, key=lambda p: str(p).casefold()):
        check_ancestors(folder)
        is_date = folder in classified if mode == "type" else bool(dates.DATE_FOLDER_RE.fullmatch(folder.name))
        automatic_sort = dates.folder_sort_key(folder) if is_date else SORT_NAME
        planned.append((folder, options.profile(is_date, automatic_sort)))
    applied, failed = [], {}
    with FolderViewStore() as store:
        for folder, (view, sort_key, ascending) in planned:
            try:
                check_ancestors(folder)
                store.apply(folder, view=view, sort_key=sort_key, ascending=ascending)
                applied.append(folder)
            except Exception as error:
                failed[folder] = str(error)
    return applied, failed
