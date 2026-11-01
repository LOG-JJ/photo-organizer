"""Central test bootstrap: all generated files belong to .work."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "src"))
os.environ["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")
from photo_organizer.paths import configure_development
configure_development()
