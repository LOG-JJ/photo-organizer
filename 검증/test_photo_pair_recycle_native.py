"""테스트용 파일 하나만 휴지통 이동 후 복원하는 Windows 통합 검증."""
from pathlib import Path
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import photo_pair_cleanup as app


with tempfile.TemporaryDirectory(prefix="pair_recycle_test_", dir=Path(__file__).parent) as temporary:
    root = Path(temporary) / "fixture photos"
    root.mkdir()
    unique = "PAIR_TEST_" + uuid.uuid4().hex
    orphan = root / (unique + ".NEF")
    orphan.write_bytes(b"generated recycle test file, not a real photograph")
    kept_raw, kept_jpg = root / "keep.NEF", root / "keep.JPG"
    kept_raw.write_bytes(b"retained raw")
    kept_jpg.write_bytes(b"retained jpg")
    scan = app.scan_folder(root)
    assert len(scan.candidates) == 1 and scan.candidates[0].path == orphan
    with contextlib.redirect_stdout(io.StringIO()):
        result = app.recycle_selected(scan, [0], "raw")
    assert result == (1, 0), result
    assert not orphan.exists()
    assert kept_raw.read_bytes() == b"retained raw"
    assert kept_jpg.read_bytes() == b"retained jpg"
    environment = os.environ.copy()
    environment["PAIR_TEST_FOLDER"] = str(root)
    environment["PAIR_TEST_NAME"] = orphan.name
    command = r'''
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject Shell.Application
$bin = $shell.NameSpace(10)
$wantedNames = @($env:PAIR_TEST_NAME, [IO.Path]::GetFileNameWithoutExtension($env:PAIR_TEST_NAME))
$items = @($bin.Items() | Where-Object {
    $_.Name -in $wantedNames -and
    $_.ExtendedProperty('System.Recycle.DeletedFrom') -eq $env:PAIR_TEST_FOLDER
})
if ($items.Count -ne 1) { throw "Expected one unique fixture in Recycle Bin, found $($items.Count)." }
$items[0].InvokeVerb('undelete')
Write-Output 'RECYCLE_BIN_ITEM_VERIFIED_AND_RESTORE_REQUESTED'
'''
    restored = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        env=environment, capture_output=True, text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    if restored.returncode:
        raise AssertionError(restored.stderr)
    for _ in range(100):
        if orphan.exists():
            break
        time.sleep(0.1)
    assert orphan.read_bytes() == b"generated recycle test file, not a real photograph"
    print(json.dumps({"native_recycle": "passed", "verified_in_recycle_bin": True,
        "restored_original_bytes": True, "paired_files_untouched": True}))
