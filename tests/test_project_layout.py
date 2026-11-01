"""Guard against generated files escaping the workspace or leaking into Git."""
from _support import ROOT
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest
from photo_organizer.paths import artifact_path, resource_root, workspace_root


class ProjectLayoutTests(unittest.TestCase):
    def test_resources_resolve_from_reorganized_source(self):
        self.assertTrue((resource_root()/"assets/fonts/NotoSansKR-Regular.ttf").is_file())
        self.assertTrue((resource_root()/"assets/icons/file_sort.ico").is_file())

    def test_generated_paths_cannot_escape_workspace(self):
        with self.assertRaises(ValueError):
            artifact_path("../../outside")
        with self.assertRaises(ValueError):
            artifact_path("reports", "../../outside.json")
        self.assertTrue(Path(tempfile.gettempdir()).is_relative_to(workspace_root()))

    @unittest.skipUnless((ROOT / ".git").exists() and shutil.which("git"), "Git checkout required")
    def test_all_output_categories_are_ignored(self):
        paths = [".work/tmp/example.JPG", ".work/reports/tests.log", ".work/previews/example.png",
                 ".work/build/example.exe", ".work/venv/pyvenv.cfg", "dist/PhotoOrganizer-Setup.exe"]
        result = subprocess.run(["git", "check-ignore", "--", *paths], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(set(result.stdout.splitlines()), set(paths))
