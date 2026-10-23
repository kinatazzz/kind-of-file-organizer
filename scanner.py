# находит файлы и запоминает их источник

import sys
from pathlib import Path


# временные файлы и загрузки
TEMPORARY_EXTENSIONS = {".part", ".crdownload", ".download", ".tmp"}


def scan_sources(
    sources: dict,
    skip_extensions: list,
    base_dir: Path,
) -> tuple[list[tuple[str, Path]], list[str]]:
   # возвращает найденные файлы и ошибки
    if not all(
        isinstance(extension, str) and extension.startswith(".")
        for extension in skip_extensions):
        raise ValueError("В skip_extensions нужны расширения с точкой: .dmg.")

    # объединяем исключения без учета регистра
    excluded = TEMPORARY_EXTENSIONS | {extension.casefold() for extension in skip_extensions}
    files = []
    errors = []

    for source_name, source_path in sources.items():
        if not isinstance(source_path, str) or not source_path.strip():
            errors.append(f"У источника «{source_name}» должен быть непустой путь.")
            continue

        # проверяем каждый источник отдельно
        try:
            folder = base_dir / Path(source_path).expanduser()
            entries = list(folder.iterdir())
        except (FileNotFoundError, NotADirectoryError):
            errors.append(f"Не найдена папка «{source_name}»: {source_path}")
            continue
        except PermissionError:
            errors.append( f"Нет доступа к папке «{source_name}»: {source_path}")
            continue
        except (OSError, ValueError, RuntimeError) as error:
            errors.append( f"Не удалось открыть папку «{source_name}»: {error}")
            continue

        # не заходим во вложенные папки
        for file_path in entries:
            if file_path.name.startswith("."):
                continue
            if file_path.suffix.casefold() in excluded:
                continue

            try:
                if file_path.is_symlink() or not file_path.is_file():
                    continue
            except OSError as error:
                errors.append(
                    f"Не удалось проверить {file_path}: {error}"
                )
                continue

            # сохраняем источник файла
            files.append((source_name, file_path))

    return files, errors


def main() -> int:
    # показывает найденные файлы и ошибки."""
    # используем готовое чтение настроек
    from organizer import BASE_DIR, CONFIG_PATH, load_config

    try:
        config = load_config(CONFIG_PATH)
        files, errors = scan_sources( config["sources"], config["skip_extensions"], BASE_DIR)
    except (OSError, ValueError) as error:
        print(f"Ошибка настроек: {error}", file=sys.stderr)
        return 1

    for source_name, file_path in files:
        print(f"[{source_name}] {file_path.name}")

    for error in errors:
        print(f"Ошибка сканирования: {error}", file=sys.stderr)

    print(f"Найдено файлов: {len(files)}")
    return 1 if errors else 0


# запускаем при прямом вызове файла
if __name__ == "__main__":
    raise SystemExit(main())
