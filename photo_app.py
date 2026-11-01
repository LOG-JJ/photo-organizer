"""설치형 프로그램의 시작점. 기록 파일을 생성하지 않습니다."""
from __future__ import annotations

import ctypes as ct
import os
import sys

from photo_version import APP_ID

_instance_handle = None


def main():
    global _instance_handle
    if os.name == "nt":
        shell = ct.WinDLL("shell32")
        shell.SetCurrentProcessExplicitAppUserModelID.argtypes = [ct.c_wchar_p]
        shell.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        kernel = ct.WinDLL("kernel32")
        kernel.CreateMutexW.argtypes = [ct.c_void_p, ct.c_int, ct.c_wchar_p]
        kernel.CreateMutexW.restype = ct.c_void_p
        _instance_handle = kernel.CreateMutexW(None, False, APP_ID)
    if len(sys.argv) > 1 and sys.argv[1] == "--verify-package":
        from photo_package_check import main as verify
        return verify(sys.argv[2:])
    try:
        from photo_organizer_gui import main as gui_main
        gui_main()
    except Exception as error:
        if os.name == "nt":
            user = ct.WinDLL("user32")
            user.MessageBoxW.argtypes = [ct.c_void_p, ct.c_wchar_p, ct.c_wchar_p, ct.c_uint]
            user.MessageBoxW(None, "프로그램을 시작하지 못했습니다.\n다시 설치한 후 실행해 주세요.\n\n" + str(error), "사진 정리", 0x10)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
