import io
import json
import plistlib
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import organizer
from macos_schedule import make_job


class LocalConfigTests(unittest.TestCase):
    def test_demo_is_isolated_repeatable_and_does_not_call_ai(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            config = organizer.load_config(organizer.CONFIG_PATH)
            config["ai"]["enabled"] = True
            (base / "config.example.json").write_text(json.dumps(config), encoding="utf-8")
            shutil.copytree(organizer.BASE_DIR / "examples", base / "examples")
            originals = {path: path.read_bytes() for path in (base / "examples").rglob("*") if path.is_file()}
            output = io.StringIO()
            with patch("rules.classify_file") as ai, redirect_stdout(output):
                self.assertEqual(organizer.run_demo(base), 0)
                first = next((base / "demo").iterdir())
                marker = first / "output/сохранить.txt"
                marker.write_text("правка пользователя", encoding="utf-8")
                self.assertEqual(organizer.run_demo(base), 0)
            ai.assert_not_called()
            self.assertEqual(len(list((base / "demo").iterdir())), 2)
            self.assertEqual(marker.read_text(encoding="utf-8"), "правка пользователя")
            self.assertEqual(originals, {path: path.read_bytes() for path in originals})
            self.assertIn("Перемещено файлов: 7", output.getvalue())
            self.assertIn("Перемещено файлов: 2", output.getvalue())
            work = first / "output/Рабочее/offersagr"
            self.assertIn("12", (work / "offersagr_отчёт.csv").read_text(encoding="utf-8"))
            self.assertIn("20", (work / "offersagr_отчёт_1.csv").read_text(encoding="utf-8"))
            self.assertEqual(len(list((first / "output/Дубликаты").iterdir())), 2)

    def test_demo_rejects_paths_outside_demo(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            config = organizer.load_config(organizer.CONFIG_PATH)
            config["sources"]["downloads"] = str(base / "real-downloads")
            (base / "config.example.json").write_text(json.dumps(config), encoding="utf-8")
            errors = io.StringIO()
            with redirect_stderr(errors):
                self.assertEqual(organizer.run_demo(base), 1)
            self.assertIn("Не удалось запустить демо", errors.getvalue())
            self.assertFalse((base / "real-downloads").exists())

    def test_demo_cli_routes_to_demo_and_rejects_other_modes(self):
        with patch("sys.argv", ["organizer.py", "--demo"]), patch.object(organizer, "run_demo", return_value=0) as demo:
            self.assertEqual(organizer.main(), 0)
            demo.assert_called_once_with(organizer.BASE_DIR)
        for args in (("--apply",), ("--ai",), ("--config", "personal.json")):
            with patch("sys.argv", ["organizer.py", "--demo", *args]), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    organizer.main()
                self.assertEqual(error.exception.code, 2)

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
