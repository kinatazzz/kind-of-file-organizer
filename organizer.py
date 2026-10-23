# читаем и проверяем настройки 

import argparse
from mover import copy_to_codex, move_file
from collections import Counter
from rules import choose_destination, make_folder_path
from scanner import scan_sources
import json
import shutil
import sys
import tempfile
from pathlib import Path

# ищем настройки рядом со скриптом
BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.example.json"

# обязательные разделы и их типы
REQUIRED_SECTIONS = {
    "sources": dict,
    "destinations": dict,
    "subjects": dict,
    "projects": dict,
    "work_extensions": list,
    "skip_extensions": list,
    "screenshot_prefixes": list,
}


def load_config(config_path: Path) -> dict:
    # читаем json и автоматически закрываем файл
    with config_path.open("r", encoding="utf-8") as config_file:
        config = json.load(config_file)

    # проверяем структуру настроек
    if not isinstance(config, dict):
        raise ValueError("Настройки должны быть JSON-объектом: { ... }.")

    for section_name, expected_type in REQUIRED_SECTIONS.items():
        if section_name not in config:
            raise ValueError(
                f"В настройках отсутствует раздел «{section_name}»."
            )

        if not isinstance(config[section_name], expected_type):
            raise ValueError(
                f"Неверный тип данных в разделе «{section_name}»."
            )

    if "ai" in config:
        if not isinstance(config["ai"], dict):
            raise ValueError("Раздел ai должен быть JSON-объектом.")
        if type(config["ai"].get("enabled", False)) is not bool:
            raise ValueError("В ai.enabled нужно true или false.")

    return config
    
def show_preview(config: dict, base_dir: Path) -> int:
    # показывает план без изменения файлов
    # находим файлы в источниках
    try:
        files, errors = scan_sources(
            config["sources"], config["skip_extensions"], base_dir
        )
    except ValueError as error:
        print(
            f"Ошибка настроек сканирования: {error}",
            file=sys.stderr,
        )
        return 1

    counts = Counter()
    print("\nПредварительное распределение:")

    # выбираем папки для каждого файла
    for source_name, file_path in files:
        try:
            destination, codex_folder = choose_destination(
                file_path, source_name, config, base_dir
            )
        except ValueError as error:
            errors.append(
                f"[{source_name}] {file_path.name}: {error}"
            )
            continue

        # показываем план без перемещения
        print(f"\n[{source_name}] {file_path}")
        if destination is None:
            print("  Пропустить")
            continue

        counts["planned"] += 1
        print(f"  Переместить в: {destination}")

        if codex_folder is not None:
            counts["copies"] += 1
            print(f"  Копия в Codex: {codex_folder}")

    for error in errors:
        print(f"Ошибка: {error}", file=sys.stderr)

    print(f"\nНайдено файлов: {len(files)}")
    print(f"В плане распределения: {counts['planned']}")
    print(f"Дополнительных копий: {counts['copies']}")
    print(f"Ошибок: {len(errors)}")
    print("Это предварительный просмотр: файлы остаются на местах.")

    return 1 if errors else 0

def apply_distribution(config: dict, base_dir: Path) -> int:
    # проверяем папки до перемещения
    try:
        duplicates_folder = make_folder_path(
            config["destinations"].get("duplicates"), base_dir
        ).resolve()
        files, errors = scan_sources(
            config["sources"], config["skip_extensions"], base_dir
        )
        source_folders = {
            make_folder_path(folder, base_dir).resolve()
            for folder in config["sources"].values()
            if isinstance(folder, str) and folder.strip()
        }
        if duplicates_folder in source_folders:
            raise ValueError("Папка дубликатов совпадает с источником.")
    except (OSError, ValueError) as error:
        print(f"Ошибка подготовки: {error}", file=sys.stderr)
        return 1

    counts = Counter()
    print("\nРаспределение файлов:")

    for source_name, file_path in files:
        try:
            destination, codex_folder = choose_destination(
                file_path, source_name, config, base_dir
            )
            if destination is None:
                continue

            # исключаем повторное сканирование
            for folder in (destination, codex_folder):
                if folder is None:
                    continue
                if folder.resolve() in source_folders:
                    raise ValueError("Папка назначения совпадает с источником.")
                if folder.resolve() == duplicates_folder:
                    raise ValueError("Папка назначения совпадает с папкой дубликатов.")

            print(f"\n[{source_name}] {file_path}")

            # сохраняем копию до удаления исходника
            if (
                codex_folder is not None
                and codex_folder.resolve() != destination.resolve()
            ):
                copy_path, created = copy_to_codex(file_path, codex_folder)
                if created:
                    counts["copies"] += 1
                    print(f"  Создана копия в Codex: {copy_path}")
                else:
                    counts["existing_copies"] += 1
                    print(f"  Копия уже есть в Codex: {copy_path}")

            target, is_duplicate = move_file(
                file_path, destination, duplicates_folder
            )
        except (OSError, ValueError) as error:
            errors.append(f"[{source_name}] {file_path.name}: {error}")
            continue

        # считаем только успешные перемещения
        counts["moved"] += 1
        if is_duplicate:
            counts["duplicates"] += 1
            print(f"  Дубликат перемещён в: {target}")
        else:
            print(f"  Перемещён в: {target}")

    for error in errors:
        print(f"Ошибка: {error}", file=sys.stderr)

    print(f"\nНайдено файлов: {len(files)}")
    print(f"Перемещено файлов: {counts['moved']}")
    print(f"Из них дубликатов: {counts['duplicates']}")
    print(f"Создано копий в Codex: {counts['copies']}")
    print(f"Копий уже существовало: {counts['existing_copies']}")
    print(f"Ошибок: {len(errors)}")
    return 1 if errors else 0

def demo_folder(folder: str, run_dir: Path) -> str:
    # ограничиваем тестовые пути папкой текущего запуска
    path = (run_dir / Path(folder).relative_to("demo")).resolve()
    path.relative_to(run_dir)
    return str(path)


def run_demo(base_dir: Path) -> int:
    try:
        config = load_config(base_dir / "config.example.json")
        config.setdefault("ai", {})["enabled"] = False
        demo_root = base_dir / "demo"
        demo_root.mkdir(exist_ok=True)
        run_dir = Path(tempfile.mkdtemp(prefix="run-", dir=demo_root)).resolve()
        for section in ("sources", "destinations"):
            config[section] = {
                name: demo_folder(folder, run_dir)
                for name, folder in config[section].items()
            }
        for project in config["projects"].values():
            project["codex_folder"] = demo_folder(project["codex_folder"], run_dir)
        with (run_dir / "config.json").open("x", encoding="utf-8") as file:
            json.dump(config, file, ensure_ascii=False, indent=2)

        # проверяем оба набора обычной сортировкой
        for folder, label in (("input", "первый набор"), ("second_run", "повторная загрузка")):
            shutil.copytree(base_dir / "examples" / folder, run_dir / "input", dirs_exist_ok=True)
            print(f"\nДемонстрация: {label}")
            if folder == "input" and show_preview(config, run_dir):
                return 1
            if apply_distribution(config, run_dir):
                return 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Не удалось запустить демо: {error}", file=sys.stderr)
        return 1
    print(f"\nГотово. Результаты: {run_dir / 'output'}")
    print(f"Дополнительные копии: {run_dir / 'codex'}")
    print(f"Настройки этого запуска: {run_dir / 'config.json'}")
    return 0


def main() -> int:
    # выбираем режим запуска
    parser = argparse.ArgumentParser(description="Органайзер файлов")
    parser.add_argument(
        "--apply", action="store_true", help="переместить файлы"
    )
    parser.add_argument(
        "--ai", action="store_true", help="анализировать неизвестные файлы через Codex"
    )
    parser.add_argument(
        "--config", type=Path, default=CONFIG_PATH, help="путь к файлу настроек"
    )
    parser.add_argument(
        "--demo", action="store_true", help="подготовить и распределить тестовые файлы"
    )
    args = parser.parse_args()
    if args.demo:
        if args.apply or args.ai or args.config != CONFIG_PATH:
            parser.error("--demo запускается отдельно от --apply, --ai и --config")
        return run_demo(BASE_DIR)
    config_path = args.config
    # обрабатываем ошибки чтения и проверки
    try:
        config_path = make_folder_path(str(config_path), BASE_DIR)
        config = load_config(config_path)
    except FileNotFoundError:
        error_message = f"Не найден файл настроек: {config_path}"
    except PermissionError:
        error_message = f"Нет доступа к файлу настроек: {config_path}"
    except IsADirectoryError:
        error_message = (
            f"Вместо файла настроек указана папка: {config_path}"
        )
    except UnicodeDecodeError:
        error_message = "Сохраните файл настроек в кодировке UTF-8."
    except json.JSONDecodeError as error:
        error_message = (
            f"Ошибка JSON: строка {error.lineno}, "
            f"столбец {error.colno}. "
            "Проверьте кавычки, запятые и скобки."
        )
    except ValueError as error:
        error_message = str(error)
    except OSError as error:
        error_message = f"Не удалось прочитать файл настроек: {error}"
    else:
        print("Настройки успешно загружены.")
        print(f"Папок-источников: {len(config['sources'])}")
        print(f"Предметов: {len(config['subjects'])}")
        print(f"Проектов Codex: {len(config['projects'])}")
        if args.ai:
            config.setdefault("ai", {})["enabled"] = True
        if args.apply:
            return apply_distribution(config, BASE_DIR)
        return show_preview(config, BASE_DIR)


    print(f"Ошибка: {error_message}", file=sys.stderr)
    return 1  # ошибка


# запускаем при прямом вызове файла
if __name__ == "__main__":
    raise SystemExit(main())
