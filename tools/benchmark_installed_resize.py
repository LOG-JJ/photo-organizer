"""설치된 앱의 빈 창을 크기 변경하며 응답 지연과 CPU 시간을 측정합니다."""
import argparse
import ctypes as ct
from ctypes import wintypes as wt
import json
from pathlib import Path
import statistics
import subprocess
import time
from _support import ROOT

parser = argparse.ArgumentParser()
parser.add_argument("exe", type=Path)
parser.add_argument("--frames", type=int, default=32)
args = parser.parse_args()
user = ct.WinDLL("user32", use_last_error=True)
kernel = ct.WinDLL("kernel32", use_last_error=True)
callback_type = ct.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user.EnumWindows.argtypes = [callback_type, wt.LPARAM]
user.GetWindowThreadProcessId.argtypes = [wt.HWND, ct.POINTER(wt.DWORD)]
user.IsWindowVisible.argtypes = [wt.HWND]
user.SetWindowTextW.argtypes = [wt.HWND, wt.LPCWSTR]
user.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ct.c_int, ct.c_int, ct.c_int, ct.c_int, wt.UINT]
user.SendMessageTimeoutW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT, ct.POINTER(ct.c_size_t)]
user.SendMessageTimeoutW.restype = ct.c_ssize_t
user.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
kernel.GetProcessTimes.argtypes = [wt.HANDLE] + [ct.POINTER(wt.FILETIME)] * 4


def find_window(pid):
    found = []
    @callback_type
    def collect(hwnd, unused):
        owner = wt.DWORD()
        user.GetWindowThreadProcessId(hwnd, ct.byref(owner))
        if owner.value == pid and user.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True
    user.EnumWindows(collect, 0)
    return found[0] if found else None


def cpu_ms(process):
    times = [wt.FILETIME() for _ in range(4)]
    assert kernel.GetProcessTimes(wt.HANDLE(int(process._handle)), *(ct.byref(value) for value in times))
    return sum((value.dwHighDateTime << 32) | value.dwLowDateTime for value in times[2:]) / 10000


process = subprocess.Popen([str(args.exe)], cwd=args.exe.parent, creationflags=subprocess.CREATE_NO_WINDOW)
hwnd = None
try:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        hwnd = find_window(process.pid)
        if hwnd:
            break
        assert process.poll() is None, "Program exited before opening its window"
        time.sleep(.02)
    assert hwnd, "Program window did not open"
    user.SetWindowTextW(hwnd, "사진 정리 — 크기 조절 성능 확인")
    time.sleep(.3)
    start = time.perf_counter()
    cpu_start = cpu_ms(process)
    samples = []
    for frame in range(args.frames):
        half = max(1, (args.frames - 1) / 2)
        fraction = min(frame, args.frames - 1 - frame) / half
        before = time.perf_counter()
        assert user.SetWindowPos(hwnd, None, 30, 30, 1530 + round(270 * fraction), 1000 + round(200 * fraction), 0x14)
        response = ct.c_size_t()
        assert user.SendMessageTimeoutW(hwnd, 0, 0, 0, 3, 3000, ct.byref(response)), "Resize blocked the UI thread"
        samples.append((time.perf_counter() - before) * 1000)
        time.sleep(.01)
    time.sleep(.1)
    print(json.dumps({"exe": str(args.exe), "frames": args.frames,
        "wall_ms": round((time.perf_counter() - start) * 1000, 1), "cpu_ms": round(cpu_ms(process) - cpu_start, 1),
        "median_response_ms": round(statistics.median(samples), 2),
        "p95_response_ms": round(sorted(samples)[int(.95 * (len(samples) - 1))], 2),
        "max_response_ms": round(max(samples), 2)}, ensure_ascii=False), flush=True)
finally:
    if hwnd and process.poll() is None:
        user.PostMessageW(hwnd, 0x10, 0, 0)
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
