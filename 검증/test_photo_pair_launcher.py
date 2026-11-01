"""공백과 &가 있는 경로를 명령줄에서 검사하고 취소하는 실행 검증."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

base = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="pair_launcher_", dir=Path(__file__).parent) as temporary:
    root = Path(temporary) / "test photos & dates"
    root.mkdir()
    raw = root / "DSC_001.NEF"
    raw.write_bytes(b"generated launcher test")
    jpg = root / "DSC_002.JPG"
    jpg.write_bytes(b"generated JPG launcher test")
    before = raw.read_bytes(), raw.stat().st_mtime_ns
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    command = [sys.executable, "-X", "utf8", str(base / "photo_pair_cleanup.py"),
        str(root)]
    result = subprocess.run(command, input="A\n\n\n", capture_output=True,
        encoding="utf-8", timeout=30, env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "RAW/JPG 짝 없는 파일 정리" in result.stdout, result.stdout
    assert "정리 후보: 2개" in result.stdout, result.stdout
    assert "[RAW]" in result.stdout and "[JPG]" in result.stdout, result.stdout
    assert "최종 확인> 취소했습니다." in result.stdout, result.stdout
    assert before == (raw.read_bytes(), raw.stat().st_mtime_ns)
    assert not list(Path(temporary).rglob("*.csv"))
    print("PASS: command-line mode, UTF-8 Korean, path with spaces and &, final cancellation, photos unchanged")
