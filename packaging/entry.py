"""PyInstaller-only entry point; development tools are outside the package."""
from photo_organizer.app import main

if __name__ == "__main__":
    raise SystemExit(main())
