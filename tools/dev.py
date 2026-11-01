"""Small development entry point. Logs, fixtures, caches and builds stay in .work."""
from _support import ROOT
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from photo_organizer.paths import artifact_path, workspace_root


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    tests = commands.add_parser("test")
    tests.add_argument("--pattern", default="test_*.py")
    commands.add_parser("build")
    verification = commands.add_parser("verify")
    verification.add_argument("--exe", type=Path, default=artifact_path("build/dist/PhotoOrganizer") / "PhotoOrganizer.exe")
    commands.add_parser("clean")
    args = parser.parse_args()
    if args.command == "clean":
        workspace = workspace_root().resolve()
        for name in ("tmp", "previews", "reports", "cache"):
            folder = workspace / name
            if folder.exists():
                if not folder.resolve().is_relative_to(workspace):
                    raise ValueError("Cleanup path left .work")
                shutil.rmtree(folder)
        print("Cleared .work temporary files; build tools and installer retained.")
        return 0
    if args.command == "test":
        command = [sys.executable, "-B", "-X", "utf8", "-m", "unittest", "discover",
                   "-s", "tests", "-p", args.pattern, "-v"]
        report = artifact_path("reports", "tests.log")
    elif args.command == "build":
        command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                   str(ROOT / "packaging" / "build.ps1")]
        report = artifact_path("reports", "build.log")
    else:
        report = artifact_path("reports", "package.json")
        command = [str(args.exe.resolve()), "--verify-package", "--report", str(report)]
        result = subprocess.run(command, cwd=ROOT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        data = json.loads(report.read_text(encoding="utf-8"))
        if not data.get("passed"):
            print(data.get("error", data))
            return 1
        bundle = args.exe.resolve().parent
        forbidden = {".work", "tests", "tools", "packaging", "__pycache__"}
        leaked = [str(p.relative_to(bundle)) for p in bundle.rglob("*")
                  if forbidden.intersection(p.relative_to(bundle).parts)]
        if leaked:
            raise RuntimeError(f"Development artifacts in package: {leaked[:5]}")
        print(f"Package passed; no development artifacts. Report: {report}")
        return result.returncode
    with report.open("w", encoding="utf-8") as output:
        result = subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
                                encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1"})
    lines = report.read_text(encoding="utf-8", errors="replace").splitlines()
    print("\n".join(lines[-10:]))
    print(f"Full report: {report}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
