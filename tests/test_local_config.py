import io
import json
import plistlib
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import organizer
from macos_schedule import make_job


class LocalConfigTests(unittest.TestCase):
    def test_cli_uses_selected_config_without_moving(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "personal settings.json"
            config = {
                key: expected_type()
                for key, expected_type in organizer.REQUIRED_SECTIONS.items()
            }
            path.write_text(json.dumps(config), encoding="utf-8")
            with (
                patch("sys.argv", ["organizer.py", "--config", str(path)]),
                patch.object(organizer, "show_preview", return_value=0) as preview,
                patch.object(organizer, "apply_distribution") as apply,
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(organizer.main(), 0)
            self.assertEqual(preview.call_args.args[0], config)
            apply.assert_not_called()

    def test_missing_config_error_names_selected_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "missing.json"
            errors = io.StringIO()
            with patch("sys.argv", ["organizer.py", "--config", str(path)]), redirect_stderr(errors):
                self.assertEqual(organizer.main(), 1)
            self.assertIn(str(path), errors.getvalue())

    def test_schedule_preserves_venv_python_and_paths_with_spaces(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            python = base / ".venv/bin/python"
            python.parent.mkdir(parents=True)
            python.symlink_to("/usr/bin/python3")
            config = base / "personal settings.json"
            job = make_job(base, config, python, base, base / "bin/codex")
            job = plistlib.loads(plistlib.dumps(job))
            self.assertEqual(job["ProgramArguments"][0], str(python))
            self.assertIn(str(config), job["ProgramArguments"])
            self.assertIn("--apply", job["ProgramArguments"])
            self.assertEqual(job["StartInterval"], 300)
            self.assertFalse(job["RunAtLoad"])
            self.assertTrue(job["EnvironmentVariables"]["PATH"].startswith(str(base / "bin")))


if __name__ == "__main__":
    unittest.main()
