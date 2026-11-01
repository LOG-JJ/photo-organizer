"""Launch from source without installing the package or creating bytecode caches."""
from pathlib import Path
import sys

sys.dont_write_bytecode = True
for stream in (sys.stdout, sys.stderr):
    if stream is not None and hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from photo_organizer.app import main

if __name__ == "__main__":
    raise SystemExit(main())
