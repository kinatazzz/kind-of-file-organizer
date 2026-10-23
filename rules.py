# выбор папок назначения

from pathlib import Path
from typing import Optional

from ai_classifier import classify_file


# допустимые разделители после ключа
KEY_SEPARATORS = " _-.–—"
WORK_OTHER_FOLDER = "Остальное"


def find_match(file_stem: str, groups: dict) -> Optional[str]:
    # находит группу по ключу
    file_stem = file_stem.casefold()
    matches = []

    for name, settings in groups.items():
        keys = (
            settings.get("keys")
            if isinstance(settings, dict)
            else settings
        )
        if not isinstance(keys, list):
            raise ValueError(
                f"Ключи для «{name}» должны быть списком."
            )

        for key in keys:
            if not isinstance(key, str) or not key.strip():
                raise ValueError(
                    f"Для «{name}» указан пустой или неверный ключ."
                )

            key = key.strip().casefold()
            if not file_stem.startswith(key):
                continue

            # проверяем границу после ключа
            remainder = file_stem[len(key):]
            if (
                not remainder
                or remainder[0] in KEY_SEPARATORS
                or key[-1] in KEY_SEPARATORS
            ):
                matches.append((len(key), name))

    if not matches:
        return None

    # выбираем самое точное совпадение
    longest = max(length for length, name in matches)
    names = {
        name for length, name in matches
        if length == longest
    }
    if len(names) > 1:
        raise ValueError(
            f"Неоднозначные ключи для файла «{file_stem}»."
        )

    return names.pop()


def make_folder_path(folder_path: str, base_dir: Path) -> Path:
    # cобирает путь к папке
    if not isinstance(folder_path, str) or not folder_path.strip():
        raise ValueError(
            "В настройках папки нужен непустой путь."
        )

    try:
        return base_dir / Path(folder_path).expanduser()
    except RuntimeError as error:
        raise ValueError(
            f"Не удалось определить домашнюю папку: {folder_path}"
        ) from error


def ai_destination(
    section: str, name: str, config: dict, base_dir: Path,
) -> tuple[Path, Optional[Path]]:
    subject = name if section == "subjects" else None
    project = name if section == "projects" else None

    # связываем предмет с его проектом
    if subject is not None:
        matches = {
            find_match(key, config["projects"])
            for key in config["subjects"][subject]
        } - {None}
        if len(matches) > 1:
            raise ValueError("Для предмета найдено несколько проектов Codex.")
        project = next(iter(matches), None)
    elif project is not None:
        matches = {
            find_match(key, config["subjects"])
            for key in config["projects"][project]["keys"]
        } - {None}
        if len(matches) > 1:
            raise ValueError("Для проекта найдено несколько учебных предметов.")
        subject = next(iter(matches), None)

    codex_folder = None
    if project is not None:
        codex_folder = make_folder_path(
            config["projects"][project].get("codex_folder"), base_dir
        )
    if subject is not None:
        folder = make_folder_path(config["destinations"].get("education"), base_dir)
        return folder / subject, codex_folder

    folder = make_folder_path(config["destinations"].get("work"), base_dir)
    return folder / name, codex_folder


def choose_destination(
    file_path: Path,
    source_name: str,
    config: dict,
    base_dir: Path,
) -> tuple[Optional[Path], Optional[Path]]:
   # выбирает папки перемещения и копирования
    for section in ("skip_extensions", "work_extensions"):
        if not all(
            isinstance(extension, str) and extension.startswith(".")
            for extension in config[section]
        ):
            raise ValueError(
                f"В {section} нужны расширения с точкой."
            )

    if not all(
        isinstance(prefix, str) and prefix.strip()
        for prefix in config["screenshot_prefixes"]
    ):
        raise ValueError(
            "Префиксы скриншотов должны быть непустыми строками."
        )

    extension = file_path.suffix.casefold()
    skipped = {
        item.casefold() for item in config["skip_extensions"]
    }
    if extension in skipped:
        return None, None

    if source_name not in config["sources"]:
        raise ValueError(
            f"Неизвестный источник: {source_name}"
        )

    subject = find_match(file_path.stem, config["subjects"])
    project = find_match(file_path.stem, config["projects"])
    destinations = config["destinations"]
    codex_folder = None

    # готовим путь дополнительной копии
    if project is not None:
        settings = config["projects"][project]
        if not isinstance(settings, dict):
            raise ValueError(f"Настройки проекта «{project}» должны быть словарём.")
        codex_folder = make_folder_path( settings.get("codex_folder"), base_dir)

    # предмет имеет первый приоритет
    if subject is not None:
        folder = make_folder_path(destinations.get("education"), base_dir)
        return folder / subject, codex_folder

    if project is not None:
        folder = make_folder_path(destinations.get("work"), base_dir)
        return folder / project, codex_folder

    # скриншоты определяем по началу имени
    if any(
        file_path.stem.casefold().startswith(prefix.casefold())
        for prefix in config["screenshot_prefixes"]
    ):
        return make_folder_path(
            destinations.get("screenshots"), base_dir
        ), None

    # просим codex только после обычных ключей
    if config.get("ai", {}).get("enabled", False):
        category = classify_file(file_path, config)
        if category is not None:
            return ai_destination(*category, config, base_dir)

    if source_name == "telegram":
        return make_folder_path(
            destinations.get("telegram_other"), base_dir
        ), None

    work_extensions = {
        item.casefold() for item in config["work_extensions"]
    }
    if source_name == "downloads" and extension in work_extensions:
        folder = make_folder_path(
            destinations.get("work"), base_dir
        )
        return folder / WORK_OTHER_FOLDER, None

    return make_folder_path(
        destinations.get("other"), base_dir
    ), None
