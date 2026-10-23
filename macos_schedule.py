import argparse
import plistlib
import shutil
import sys
from pathlib import Path

from organizer import BASE_DIR, load_config
from rules import make_folder_path


LABEL = "local.kind-of-file-organizer"
INTERVAL_SECONDS = 5 * 60


def make_job(
    project_dir: Path,
    config_path: Path,
    python_path: Path,
    home: Path,
    codex_path: Path,
) -> dict:
    # сохраняем путь python из виртуального окружения
    log_dir = home / "Library/Logs/kind-of-file-organizer"
    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(python_path.absolute()), "-u", str(project_dir / "organizer.py"),
            "--config", str(config_path), "--apply",
        ],
        "WorkingDirectory": str(project_dir),
        "StartInterval": INTERVAL_SECONDS,
        "RunAtLoad": False,
        "Umask": 0o077,
        # добавляем codex в путь фонового процесса
        "EnvironmentVariables": {
            "HOME": str(home),
            "PATH": ":".join(dict.fromkeys([
                str(codex_path.parent), str(home / ".local/bin"),
                "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin",
            ])),
        },
        "StandardOutPath": str(log_dir / "organizer.log"),
        "StandardErrorPath": str(log_dir / "errors.log"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Подготовка таймера macOS")
    parser.add_argument("--config", default="config.local.json")
    parser.add_argument("--output", default="organizer.plist")
    args = parser.parse_args()
    try:
        config_path = make_folder_path(args.config, BASE_DIR).resolve()
        config = load_config(config_path)
        codex = shutil.which("codex")
        if config.get("ai", {}).get("enabled", False) and codex is None:
            raise ValueError("Не найден Codex CLI. Проверь команду codex login status.")
        job = make_job(
            BASE_DIR, config_path, Path(sys.executable), Path.home(),
            Path(codex) if codex else Path.home() / ".local/bin/codex",
        )
        output_path = make_folder_path(args.output, BASE_DIR)
        # создаём расписание без включения таймера
        with output_path.open("xb") as output:
            plistlib.dump(job, output, sort_keys=False)
    except FileExistsError:
        print("Файл расписания уже есть: укажи другой --output.", file=sys.stderr)
        return 1
    except (OSError, ValueError) as error:
        print(f"Не удалось подготовить таймер: {error}", file=sys.stderr)
        return 1
    print(f"Подготовлен файл: {output_path}")
    print("Интервал: 5 минут. Таймер пока не включён.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
