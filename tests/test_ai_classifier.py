import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import ai_classifier
import content_reader
import organizer
from rules import choose_destination


def pdf_with_text(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 10 100 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    data = b"%PDF-1.4\n"
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(data)
    data += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
    data += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    data += f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return data


class ClassifierTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        with (Path(__file__).resolve().parents[1] / "config.example.json").open(encoding="utf-8") as file:
            self.config = json.load(file)
        self.config["sources"] = {name: f"input/{name}" for name in self.config["sources"]}
        self.config["destinations"] = {name: f"output/{name}" for name in self.config["destinations"]}
        for number, project in enumerate(self.config["projects"].values()):
            project["codex_folder"] = f"codex/{number}"
        self.config["ai"] = {"enabled": True}
        for folder in self.config["sources"].values():
            (self.base / folder).mkdir(parents=True)
        self.file = self.base / "input/downloads/document.txt"
        self.file.write_text("Задачи на Python: словари, циклы и функции.", encoding="utf-8")
        self.answer = {
            "category": "subjects:Программирование на Питоне",
            "confidence": 0.95,
            "reason": "В документе задания по программированию.",
        }

    def choose(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return choose_destination(self.file, "downloads", self.config, self.base)

    def test_subject_content_routes_to_education_and_codex(self):
        with patch.object(ai_classifier, "ask_codex", return_value=self.answer) as request:
            destination, codex = self.choose()
        self.assertEqual(destination, self.base / "output/education/Программирование на Питоне")
        self.assertEqual(codex, self.base / self.config["projects"]["Мага | Питон"]["codex_folder"])
        payload = json.loads(request.call_args.args[0].split("\n", 1)[1])
        self.assertIn("словари", payload["content"])
        self.assertNotIn(str(self.base), request.call_args.args[0])

    def test_academic_project_answer_preserves_subject_priority(self):
        answer = {**self.answer, "category": "projects:Мага | Питон"}
        with patch.object(ai_classifier, "ask_codex", return_value=answer):
            destination, codex = self.choose()
        self.assertEqual(destination, self.base / "output/education/Программирование на Питоне")
        self.assertIsNotNone(codex)

    def test_work_project_answer_uses_configured_paths(self):
        answer = {**self.answer, "category": "projects:offersagr"}
        with patch.object(ai_classifier, "ask_codex", return_value=answer):
            destination, codex = self.choose()
        self.assertEqual(destination, self.base / "output/work/offersagr")
        self.assertEqual(codex, self.base / self.config["projects"]["offersagr"]["codex_folder"])

    def test_known_keys_screenshots_skips_and_disabled_mode_do_not_call_model(self):
        with patch("rules.classify_file") as request:
            for name in ("Питон_задание.txt", "offersagr_отчёт.csv", "Screenshot_test.png", "Питон_setup.dmg"):
                choose_destination(self.file.with_name(name), "downloads", self.config, self.base)
            self.config["ai"]["enabled"] = False
            self.choose()
        request.assert_not_called()

    def test_unsupported_video_keeps_normal_route(self):
        self.file = self.file.with_suffix(".mp4")
        with patch.object(ai_classifier, "ask_codex") as request:
            destination, codex = self.choose()
        self.assertEqual(destination, self.base / "output/work/Остальное")
        self.assertIsNone(codex)
        request.assert_not_called()

    def test_unknown_and_low_confidence_keep_source_specific_routes(self):
        for answer in (
            {**self.answer, "category": "unknown"},
            {**self.answer, "confidence": 0.2},
        ):
            with patch.object(ai_classifier, "ask_codex", return_value=answer):
                destination, codex = self.choose()
                with redirect_stdout(io.StringIO()):
                    telegram, _ = choose_destination(self.file, "telegram", self.config, self.base)
            self.assertEqual(destination, self.base / "output/work/Остальное")
            self.assertEqual(telegram, self.base / "output/telegram_other")
            self.assertIsNone(codex)

    def test_invalid_responses_cannot_choose_arbitrary_folders(self):
        answers = [
            [],
            {**self.answer, "category": "../../outside"},
            {**self.answer, "category": None},
            {**self.answer, "confidence": True},
            {**self.answer, "confidence": float("nan")},
            {**self.answer, "confidence": 2},
            {**self.answer, "reason": None},
        ]
        for answer in answers:
            with self.subTest(answer=answer), patch.object(ai_classifier, "ask_codex", return_value=answer):
                destination, codex = self.choose()
                self.assertEqual(destination, self.base / "output/work/Остальное")
                self.assertIsNone(codex)

    def test_timeout_missing_cli_and_network_errors_are_reported(self):
        errors = [subprocess.TimeoutExpired("codex", 1), FileNotFoundError("codex"), OSError("network unavailable")]
        for error in errors:
            with self.subTest(error=error), patch.object(ai_classifier, "ask_codex", side_effect=error):
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    destination, _ = choose_destination(self.file, "downloads", self.config, self.base)
                self.assertEqual(destination, self.base / "output/work/Остальное")
                self.assertIn("обычные правила", err.getvalue())
                self.assertTrue(self.file.exists())

    def test_changed_source_is_not_moved(self):
        def change_source(*args):
            self.file.write_text("Файл ещё сохраняется, его содержимое меняется.", encoding="utf-8")
            return self.answer
        with patch.object(ai_classifier, "ask_codex", side_effect=change_source):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = organizer.apply_distribution(self.config, self.base)
        self.assertEqual(code, 1)
        self.assertTrue(self.file.exists())
        self.assertFalse((self.base / "output").exists())

    def test_apply_and_duplicate_keep_one_codex_copy(self):
        original = self.file.read_bytes()
        for duplicate in (False, True):
            self.file.write_bytes(original)
            with patch.object(ai_classifier, "ask_codex", return_value=self.answer):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    code = organizer.apply_distribution(self.config, self.base)
            self.assertEqual(code, 0)
            self.assertFalse(self.file.exists())
            if duplicate:
                self.assertEqual((self.base / "output/duplicates/document.txt").read_bytes(), original)
        codex_folder = self.base / self.config["projects"]["Мага | Питон"]["codex_folder"]
        self.assertEqual(len(list(codex_folder.iterdir())), 1)

    def test_ai_flag_enables_preview_without_moving(self):
        self.config["ai"]["enabled"] = False
        path = self.base / "config.json"
        with path.open("w", encoding="utf-8") as file:
            json.dump(self.config, file, ensure_ascii=False)
        with patch.object(organizer, "BASE_DIR", self.base), patch.object(organizer, "CONFIG_PATH", path):
            with patch("sys.argv", ["organizer.py", "--ai"]):
                with patch.object(ai_classifier, "ask_codex", return_value=self.answer) as request:
                    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                        self.assertEqual(organizer.main(), 0)
        request.assert_called_once()
        self.assertTrue(self.file.exists())
        self.assertFalse((self.base / "output").exists())

    def test_process_uses_chatgpt_and_disables_tools(self):
        def fake_run(command, **kwargs):
            self.assertNotIn("CODEX_API_KEY", kwargs["env"])
            self.assertNotIn("OPENAI_API_KEY", kwargs["env"])
            if command[1:3] == ["login", "status"]:
                return subprocess.CompletedProcess(command, 0, "", "Logged in using ChatGPT")
            self.assertIn("--ignore-user-config", command)
            self.assertIn("read-only", command)
            self.assertIn("shell_tool", command)
            self.assertFalse(kwargs.get("shell", False))
            answer = Path(command[command.index("--output-last-message") + 1])
            with answer.open("w", encoding="utf-8") as file:
                json.dump(self.answer, file, ensure_ascii=False)
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(ai_classifier.subprocess, "run", side_effect=fake_run) as run:
            with patch.dict("os.environ", {"CODEX_API_KEY": "fake-test-key", "OPENAI_API_KEY": "fake-test-key"}):
                self.assertEqual(ai_classifier.ask_codex("test content", [self.answer["category"]], 10), self.answer)
        self.assertEqual(run.call_count, 2)

    def test_wrong_login_does_not_start_session(self):
        result = subprocess.CompletedProcess([], 0, "", "Logged in using an API key")
        with patch.object(ai_classifier.subprocess, "run", return_value=result) as run:
            with self.assertRaisesRegex(ValueError, "codex login"):
                ai_classifier.ask_codex("test", [self.answer["category"]], 10)
        self.assertEqual(run.call_count, 1)

    def test_project_descriptions_are_included(self):
        self.config["ai"]["descriptions"] = {"offersagr": "описание проекта для теста"}
        categories = ai_classifier.make_categories(self.config)
        self.assertEqual(categories["projects:offersagr"]["description"], "описание проекта для теста")


class ContentReaderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)

    def test_text_encodings(self):
        for encoding in ("utf-8", "utf-8-sig", "cp1251"):
            path = self.base / "data.csv"
            path.write_bytes("программирование;циклы".encode(encoding))
            self.assertEqual(content_reader.read_content(path), "программирование;циклы")

    def test_docx_text(self):
        path = self.base / "lesson.docx"
        with ZipFile(path, "w") as archive:
            archive.writestr("word/document.xml", '<w:document xmlns:w="urn:test"><w:t>Задание</w:t><w:t>Python</w:t></w:document>')
        self.assertEqual(content_reader.read_content(path), "Задание Python")

    def test_xlsx_headers_and_values(self):
        from openpyxl import Workbook
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Опрос"
        sheet.append(["NPS", "Оценка"])
        sheet.append(["Рекомендация", 10])
        path = self.base / "table.xlsx"
        workbook.save(path)
        workbook.close()
        text = content_reader.read_content(path)
        self.assertIn("Опрос", text)
        self.assertIn("NPS | Оценка", text)
        self.assertIn("Рекомендация | 10", text)

    def test_pdf_text_layer(self):
        path = self.base / "lesson.pdf"
        path.write_bytes(pdf_with_text("Python functions and dictionaries"))
        self.assertIn("Python functions", content_reader.read_content(path))

    def test_empty_unsupported_and_corrupted_documents(self):
        for suffix, data in ((".txt", b""), (".mp4", b"video"), (".docx", b"not a zip"), (".pdf", b"bad pdf")):
            path = self.base / ("broken" + suffix)
            path.write_bytes(data)
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                content_reader.read_content(path)
        path = self.base / "broken.xlsx"
        with ZipFile(path, "w") as archive:
            archive.writestr("wrong.xml", "no workbook")
        with self.assertRaises(ValueError):
            content_reader.read_content(path)

    def test_content_and_file_size_limits(self):
        path = self.base / "text.txt"
        path.write_text("a" * 100, encoding="utf-8")
        with patch.object(content_reader, "MAX_TEXT_CHARS", 10):
            self.assertEqual(content_reader.read_content(path), "a" * 10)
        with patch.object(content_reader, "MAX_FILE_BYTES", 50):
            with self.assertRaises(ValueError):
                content_reader.read_content(path)

    def test_unpacked_archive_limit(self):
        path = self.base / "large.docx"
        with ZipFile(path, "w") as archive:
            archive.writestr("word/document.xml", "a" * 1000)
        with patch.object(content_reader, "MAX_ARCHIVE_BYTES", 100):
            with self.assertRaises(ValueError):
                content_reader.read_content(path)


if __name__ == "__main__":
    unittest.main()
