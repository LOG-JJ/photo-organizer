"""Resource paths and the single development-artifact workspace."""
from pathlib import Path
import os
import sys
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))


def workspace_root() -> Path:
    explicit = os.environ.get("PHOTO_ORGANIZER_WORKSPACE")
    if explicit:
        return Path(explicit).resolve()
    if getattr(sys, "frozen", False):
        return Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "PhotoOrganizer" / ".work"
    return PROJECT_ROOT / ".work"


def artifact_path(area: str, name: str | None = None) -> Path:
    base = workspace_root().resolve()
    folder = (base / area).resolve()
    if not folder.is_relative_to(base):
        raise ValueError("Artifact path must stay inside .work")
    folder.mkdir(parents=True, exist_ok=True)
    target = (folder / name).resolve() if name else folder
    if not target.is_relative_to(folder):
        raise ValueError("Artifact name must stay inside its folder")
    return target


def configure_development() -> None:
    """Used by dev tools/diagnostics, never by ordinary installed-app startup."""
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["PHOTO_ORGANIZER_WORKSPACE"] = str(workspace_root())
    temporary = str(artifact_path("tmp"))
    os.environ["TEMP"] = os.environ["TMP"] = temporary
    tempfile.tempdir = temporary
