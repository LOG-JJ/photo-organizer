"""Windows 탐색기의 지정 폴더별 보기/정렬을 저장합니다 (추가 패키지 불필요).

SHGetViewStatePropertyBag와 PSPropertyBag API를 사용합니다.
전체 폴더 기본값이나 탐색기 프로세스는 변경하지 않습니다.
"""

from __future__ import annotations

import ctypes as ct
import os
import struct
import uuid
from dataclasses import dataclass
from pathlib import Path


SORT_NAME = ("{B725F130-47EF-101A-A5F1-02608C9EEBAC}", 10)
SORT_DATE_TAKEN = ("{14B81DA1-0135-4D31-96D9-6CBFC9671A99}", 36867)
SORT_DATE_MODIFIED = ("{B725F130-47EF-101A-A5F1-02608C9EEBAC}", 14)
SORT_DATE_CREATED = ("{B725F130-47EF-101A-A5F1-02608C9EEBAC}", 15)
SORT_SIZE = ("{B725F130-47EF-101A-A5F1-02608C9EEBAC}", 12)
SORT_KEYS = {"이름": SORT_NAME, "찍은 날짜": SORT_DATE_TAKEN, "수정한 날짜": SORT_DATE_MODIFIED,
             "만든 날짜": SORT_DATE_CREATED, "크기": SORT_SIZE}
VIEW_MODES = {
    "아주 큰 아이콘": (1, 3, 256), "큰 아이콘": (1, 3, 96), "보통 아이콘": (1, 3, 48),
    "작은 아이콘": (2, 3, 16), "목록": (3, 4, 16), "자세히": (4, 1, 16),
    "타일": (6, 2, 48), "내용": (8, 5, 32),
}


@dataclass(frozen=True)
class ExplorerOptions:
    general_view: str = "자세히"
    general_sort: str = "이름"
    general_ascending: bool = True
    date_view: str = "아주 큰 아이콘"
    date_sort: str = "자동"
    date_ascending: bool = True
    auto_apply: bool = True

    def __post_init__(self):
        if self.general_view not in VIEW_MODES or self.date_view not in VIEW_MODES:
            raise ValueError("보기 방식을 확인하세요.")
        if self.general_sort not in SORT_KEYS or self.date_sort not in {"자동", *SORT_KEYS}:
            raise ValueError("정렬 기준을 확인하세요.")

    def profile(self, date_folder: bool, automatic_sort=SORT_DATE_MODIFIED):
        if date_folder:
            return self.date_view, (automatic_sort if self.date_sort == "자동" else SORT_KEYS[self.date_sort]), self.date_ascending
        return self.general_view, SORT_KEYS[self.general_sort], self.general_ascending

# 자동으로 감지되는 폴더 형식이 바뀌어도 같은 보기를 사용합니다.
FOLDER_TYPES = (
    "{5C4F28B5-F869-4E84-8E60-F11DB97C5CC7}",  # Generic
    "{7D49D726-3C21-4F05-99AA-FDC2C9474656}",  # Documents
    "{B3690E58-E961-423B-B687-386EBFD83239}",  # Pictures
    "{5FA96407-7E77-483C-AC93-691D05850DE8}",  # Videos
    "{94D6DDCC-4A68-4175-A374-BD584A510B78}",  # Music
    "{4F01EBC5-2385-41F2-A28E-2C5C91FB56E0}",  # StorageProviderGeneric
    "{DD61BD66-70E8-48DD-9655-65C5E1AAC2D1}",  # StorageProviderDocuments
    "{71D642A9-F2B1-42CD-AD92-EB9300C7CC0A}",  # StorageProviderPictures
    "{51294DA1-D7B1-485B-9E9A-17CFFE33E187}",  # StorageProviderVideos
    "{672ECD7E-AF04-4399-875C-0290845B6247}",  # StorageProviderMusic
)


class GUID(ct.Structure):
    _fields_ = [("data1", ct.c_uint32), ("data2", ct.c_uint16),
                ("data3", ct.c_uint16), ("data4", ct.c_ubyte * 8)]

    @classmethod
    def parse(cls, value: str):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


def check_result(result: int) -> None:
    if result < 0:
        raise OSError(f"Windows 보기 설정 오류: 0x{result & 0xFFFFFFFF:08X}")


def com_method(pointer, index, result_type, *arg_types):
    table = ct.cast(pointer, ct.POINTER(ct.POINTER(ct.c_void_p))).contents
    return ct.WINFUNCTYPE(result_type, ct.c_void_p, *arg_types)(table[index])


def sort_blob(key: tuple[str, int], ascending: bool = True) -> bytes:
    # 정렬 열 개수, PROPERTYKEY, SORT_ASCENDING(1).
    # 레지스트리의 IStream 헤더는 PSPropertyBag_WriteStream이 추가합니다.
    return struct.pack("<I", 1) + uuid.UUID(key[0]).bytes_le + struct.pack("<Ii", key[1], 1 if ascending else -1)


class FolderViewStore:
    """현재 사용자/지정 폴더의 Shell property bag만 읽고 씁니다."""

    def __enter__(self):
        if os.name != "nt":
            raise OSError("탐색기 보기 설정은 Windows에서만 지원합니다.")
        self.ole = ct.WinDLL("ole32")
        self.shell = ct.WinDLL("shell32")
        self.shlwapi = ct.WinDLL("shlwapi")
        self.propsys = ct.WinDLL("propsys")
        declarations = (
            (self.ole, "CoInitializeEx", [ct.c_void_p, ct.c_uint32], ct.c_long),
            (self.ole, "CoUninitialize", [], None),
            (self.ole, "CoTaskMemFree", [ct.c_void_p], None),
            (self.shell, "SHParseDisplayName", [ct.c_wchar_p, ct.c_void_p,
                ct.POINTER(ct.c_void_p), ct.c_uint32, ct.c_void_p], ct.c_long),
            (self.shlwapi, "SHGetViewStatePropertyBag", [ct.c_void_p, ct.c_wchar_p,
                ct.c_uint32, ct.POINTER(GUID), ct.POINTER(ct.c_void_p)], ct.c_long),
            (self.shlwapi, "SHCreateMemStream", [ct.c_void_p, ct.c_uint32], ct.c_void_p),
            (self.propsys, "PSPropertyBag_WriteDWORD", [ct.c_void_p, ct.c_wchar_p, ct.c_uint32], ct.c_long),
            (self.propsys, "PSPropertyBag_ReadDWORD", [ct.c_void_p, ct.c_wchar_p, ct.POINTER(ct.c_uint32)], ct.c_long),
            (self.propsys, "PSPropertyBag_WriteStream", [ct.c_void_p, ct.c_wchar_p, ct.c_void_p], ct.c_long),
            (self.propsys, "PSPropertyBag_ReadStream", [ct.c_void_p, ct.c_wchar_p, ct.POINTER(ct.c_void_p)], ct.c_long),
        )
        for library, name, args, result in declarations:
            function = getattr(library, name)
            function.argtypes, function.restype = args, result
        check_result(self.ole.CoInitializeEx(None, 2))
        return self

    def __exit__(self, *exc):
        self.ole.CoUninitialize()

    def _bag(self, path: Path, name: str):
        pidl, bag = ct.c_void_p(), ct.c_void_p()
        iid = GUID.parse("{55272A00-42CB-11CE-8135-00AA004BB851}")  # IPropertyBag
        check_result(self.shell.SHParseDisplayName(str(path), None, ct.byref(pidl), 0, None))
        try:
            # SHGVSPB_FOLDERNODEFAULTS: 전역/상위 폴더 기본값은 변경하지 않습니다.
            check_result(self.shlwapi.SHGetViewStatePropertyBag(
                pidl, name, 0x80000005, ct.byref(iid), ct.byref(bag)))
        finally:
            self.ole.CoTaskMemFree(pidl)
        return bag

    @staticmethod
    def _release(pointer):
        com_method(pointer, 2, ct.c_uint32)(pointer)

    def _write(self, bag, name: str, value: int | bytes):
        if isinstance(value, bytes):
            buffer = ct.create_string_buffer(value)
            stream = self.shlwapi.SHCreateMemStream(buffer, len(value))
            if not stream:
                raise MemoryError("보기 설정 스트림을 만들 수 없습니다.")
            try:
                check_result(self.propsys.PSPropertyBag_WriteStream(bag, name, stream))
            finally:
                self._release(stream)
        else:
            check_result(self.propsys.PSPropertyBag_WriteDWORD(bag, name, value))

    def read_values(self, path: Path, bag_name: str, names: list[str]) -> dict:
        """설정 저장 후 property bag를 다시 열어 확인합니다."""
        bag = self._bag(path, bag_name)
        result = {}
        try:
            for name in names:
                if name == "Sort":
                    stream = ct.c_void_p()
                    check_result(self.propsys.PSPropertyBag_ReadStream(bag, name, ct.byref(stream)))
                    try:
                        buffer, count = ct.create_string_buffer(4096), ct.c_uint32()
                        check_result(com_method(stream, 3, ct.c_long, ct.c_void_p,
                            ct.c_uint32, ct.POINTER(ct.c_uint32))(
                                stream, buffer, len(buffer), ct.byref(count)))
                        result[name] = buffer.raw[:count.value]
                    finally:
                        self._release(stream)
                else:
                    value = ct.c_uint32()
                    check_result(self.propsys.PSPropertyBag_ReadDWORD(bag, name, ct.byref(value)))
                    result[name] = value.value
        finally:
            self._release(bag)
        return result

    def apply(self, path: Path, *, sort_key: tuple[str, int], details: bool | None = None,
              view: str | None = None, ascending: bool = True):
        view = view or ("자세히" if details else "아주 큰 아이콘")
        mode, logical_mode, icon_size = VIEW_MODES[view]
        values = {
            "Mode": mode,
            "LogicalViewMode": logical_mode,
            "IconSize": icon_size,
            "Sort": sort_blob(sort_key, ascending),
            "GroupView": 0,
            "GroupByKey:PID": 0,
        }
        names = ["Shell", *("Shell\\" + kind for kind in FOLDER_TYPES)]
        for name in names:
            bag = self._bag(path, name)
            try:
                for key, value in values.items():
                    self._write(bag, key, value)
            finally:
                self._release(bag)
            if self.read_values(path, name, list(values)) != values:
                raise OSError(f"탐색기 보기 설정을 저장하지 못했습니다: {path}")
