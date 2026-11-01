"""Windows 휴지통으로 파일을 보냅니다. Python 표준 라이브러리만 사용합니다.

IFileOperation 및 PreDeleteItem을 사용하며 영구 삭제로 대체하지 않습니다.
API: https://learn.microsoft.com/windows/win32/api/shobjidl_core/nn-shobjidl_core-ifileoperation
"""

from __future__ import annotations

import ctypes as ct
import os
import uuid
from pathlib import Path
from typing import Callable


class GUID(ct.Structure):
    _fields_ = [("data", ct.c_ubyte * 16)]

    @classmethod
    def parse(cls, value: str):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


def check_hresult(result: int) -> None:
    if result < 0:
        raise OSError(f"휴지통 작업 실패: 0x{result & 0xFFFFFFFF:08X}")


def method(pointer, index, result_type, *argument_types):
    table = ct.cast(pointer, ct.POINTER(ct.POINTER(ct.c_void_p))).contents
    return ct.WINFUNCTYPE(result_type, ct.c_void_p, *argument_types)(table[index])


class RecycleSink:
    """휴지통을 사용할 수 없거나 파일이 바뀌었으면 Windows 작업을 거부합니다."""

    def __init__(self, guard: Callable[[], None]):
        ptr, uint, hr = ct.c_void_p, ct.c_uint32, ct.c_long
        self.error = ""
        self.completed = False
        self.references = 1
        self.guard = guard
        self.callbacks = []
        self.table = (ptr * 19)()
        self.instance = (ptr * 1)(ct.addressof(self.table))
        self.pointer = ct.cast(self.instance, ptr)

        def query(this, iid, destination):
            supported = {
                uuid.UUID("00000000-0000-0000-c000-000000000046").bytes_le,
                uuid.UUID("04b0f1a7-9490-44bc-96e1-4296a31252e2").bytes_le,
            }
            if ct.string_at(iid, 16) not in supported:
                destination[0] = None
                return -2147467262  # E_NOINTERFACE
            destination[0] = self.pointer.value
            self.references += 1
            return 0

        def add_ref(this):
            self.references += 1
            return self.references

        def release(this):
            self.references -= 1
            return self.references

        def before_delete(this, flags, item):
            if not flags & 0x80:  # TSF_DELETE_RECYCLE_IF_POSSIBLE
                self.error = "휴지통을 사용할 수 없어 중단했습니다. 영구 삭제하지 않습니다."
                return -2147467259  # E_FAIL
            try:
                self.guard()
            except Exception as error:
                self.error = str(error)
                return -2147467259
            return 0

        def after_delete(this, flags, item, result, recycled_item):
            if result < 0:
                self.error = f"휴지통 작업 실패: 0x{result & 0xFFFFFFFF:08X}"
            elif not recycled_item:
                self.error = "휴지통 이동 결과를 확인하지 못했습니다."
            else:
                self.completed = True
            return 0

        def ok(*args):
            return 0

        # IUnknown(3) + IFileOperationProgressSink(16), SDK의 vtable 순서.
        declarations = [
            (hr, [ptr, ct.POINTER(GUID), ct.POINTER(ptr)], query),
            (uint, [ptr], add_ref), (uint, [ptr], release),
            (hr, [ptr], ok), (hr, [ptr, hr], ok),
            (hr, [ptr, uint, ptr, ptr], ok),
            (hr, [ptr, uint, ptr, ptr, hr, ptr], ok),
            (hr, [ptr, uint, ptr, ptr, ptr], ok),
            (hr, [ptr, uint, ptr, ptr, ptr, hr, ptr], ok),
            (hr, [ptr, uint, ptr, ptr, ptr], ok),
            (hr, [ptr, uint, ptr, ptr, ptr, hr, ptr], ok),
            (hr, [ptr, uint, ptr], before_delete),
            (hr, [ptr, uint, ptr, hr, ptr], after_delete),
            (hr, [ptr, uint, ptr, ptr], ok),
            (hr, [ptr, uint, ptr, ptr, ptr, uint, hr, ptr], ok),
            (hr, [ptr, uint, uint], ok),
            (hr, [ptr], ok), (hr, [ptr], ok), (hr, [ptr], ok),
        ]
        for index, (result, args, function) in enumerate(declarations):
            callback = ct.WINFUNCTYPE(result, *args)(function)
            self.callbacks.append(callback)
            self.table[index] = ct.cast(callback, ptr).value


class RecycleBin:
    def __enter__(self):
        if os.name != "nt":
            raise OSError("휴지통 이동은 Windows 8 이상에서만 지원합니다.")
        self.ole = ct.WinDLL("ole32")
        self.shell = ct.WinDLL("shell32")
        self.ole.CoInitializeEx.argtypes = [ct.c_void_p, ct.c_uint32]
        self.ole.CoInitializeEx.restype = ct.c_long
        self.ole.CoUninitialize.argtypes = []
        self.ole.CoUninitialize.restype = None
        self.ole.CoCreateInstance.argtypes = [ct.POINTER(GUID), ct.c_void_p,
            ct.c_uint32, ct.POINTER(GUID), ct.POINTER(ct.c_void_p)]
        self.ole.CoCreateInstance.restype = ct.c_long
        self.shell.SHCreateItemFromParsingName.argtypes = [ct.c_wchar_p, ct.c_void_p,
            ct.POINTER(GUID), ct.POINTER(ct.c_void_p)]
        self.shell.SHCreateItemFromParsingName.restype = ct.c_long
        check_hresult(self.ole.CoInitializeEx(None, 2))  # STA
        return self

    def __exit__(self, *exc):
        self.ole.CoUninitialize()

    def recycle(self, path: Path, guard: Callable[[], None]) -> None:
        guard()
        operation, item = ct.c_void_p(), ct.c_void_p()
        sink = RecycleSink(guard)
        clsid = GUID.parse("3ad05575-8857-4850-9277-11b85bdb8e09")
        iid = GUID.parse("947aab5f-0a5c-4c13-b4d6-4bf7836fc9f8")
        shell_iid = GUID.parse("43826d1e-e718-42ee-bc55-a1e261c37bfe")
        check_hresult(self.ole.CoCreateInstance(
            ct.byref(clsid), None, 1, ct.byref(iid), ct.byref(operation)))
        try:
            # RECYCLEONDELETE + ADDUNDORECORD + EARLYFAILURE + NOERRORUI + SILENT.
            # 콘솔에서 확인한 작업이며, 영구 삭제 대체는 sink에서 거부합니다.
            flags = 0x00080000 | 0x20000000 | 0x00100000 | 0x0400 | 0x0004 | 0x0010
            check_hresult(method(operation, 5, ct.c_long, ct.c_uint32)(operation, flags))
            check_hresult(self.shell.SHCreateItemFromParsingName(
                str(path), None, ct.byref(shell_iid), ct.byref(item)))
            check_hresult(method(operation, 18, ct.c_long, ct.c_void_p, ct.c_void_p)(
                operation, item, sink.pointer))
            result = method(operation, 21, ct.c_long)(operation)
            if sink.error:
                raise OSError(sink.error)
            check_hresult(result)
            aborted = ct.c_int()
            check_hresult(method(operation, 22, ct.c_long, ct.POINTER(ct.c_int))(
                operation, ct.byref(aborted)))
            if aborted.value or not sink.completed or path.exists():
                raise OSError("휴지통 이동이 취소되었거나 완료되지 않았습니다.")
        finally:
            if item:
                method(item, 2, ct.c_uint32)(item)
            method(operation, 2, ct.c_uint32)(operation)
