import hashlib
import shutil
from pathlib import Path
from typing import Optional


CHUNK_SIZE = 1024 * 1024


def file_hash(file_path: Path) -> str:
    digest = hashlib.sha256()

    # читаем по частям
    with file_path.open("rb") as file:
        while block := file.read(CHUNK_SIZE):
            digest.update(block)

    return digest.hexdigest()


def find_duplicate(file_path: Path, folder: Path) -> Optional[Path]:
    if file_path.is_symlink():
        raise ValueError(f"Нельзя обрабатывать ссылку: {file_path}")

    file_size = file_path.stat().st_size
    if not folder.exists():
        return None

    source_hash = None

    for candidate in folder.iterdir():
        if candidate.is_symlink() or not candidate.is_file():
            continue

        # сначала сравниваем размеры
        if candidate.stat().st_size != file_size:
            continue

        if source_hash is None:
            source_hash = file_hash(file_path)

        if file_hash(candidate) == source_hash:
            return candidate

    return None


def copy_unique(file_path: Path, folder: Path) -> Path:
    if file_path.is_symlink():
        raise ValueError(f"Нельзя обрабатывать ссылку: {file_path}")

    before = file_path.stat()
    folder.mkdir(parents=True, exist_ok=True)
    number = 0

    # не перезаписываем существующие файлы
    while True:
        name = file_path.name if number == 0 else (
            f"{file_path.stem}_{number}{file_path.suffix}"
        )
        target = folder / name

        try:
            target_file = target.open("xb")
        except FileExistsError:
            number += 1
        else:
            break

    try:
        with target_file, file_path.open("rb") as source_file:
            shutil.copyfileobj(source_file, target_file, CHUNK_SIZE)

        # замечаем изменения при копировании
        after = file_path.stat()
        if (
            before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ino != after.st_ino
        ):
            raise OSError(f"Файл изменился при копировании: {file_path}")

        shutil.copystat(file_path, target)
    except OSError:
        # убираем незавершённую копию
        target.unlink(missing_ok=True)
        raise

    return target


def move_file(
    file_path: Path,
    destination: Path,
    duplicates_folder: Path,
) -> tuple[Path, bool]:
    if file_path.parent.resolve() == destination.resolve():
        raise ValueError("Источник и папка назначения совпадают.")

    if destination.resolve() == duplicates_folder.resolve():
        raise ValueError("Папка назначения совпадает с папкой дубликатов.")

    duplicate = find_duplicate(file_path, destination)
    folder = duplicates_folder if duplicate is not None else destination

    # удаляем исходник после успешной копии
    target = copy_unique(file_path, folder)
    try:
        file_path.unlink()
    except OSError as error:
        raise OSError(
            f"Копия сохранена в {target}, но исходник не удалён: {error}"
        ) from error

    return target, duplicate is not None


def copy_to_codex(file_path: Path, codex_folder: Path) -> tuple[Path, bool]:
    # повторную копию не создаём
    existing = find_duplicate(file_path, codex_folder)
    if existing is not None:
        return existing, False

    return copy_unique(file_path, codex_folder), True
