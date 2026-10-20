import os
import re
from pathlib import Path
from threading import Event
from urllib.parse import urlparse

import gdown

from tribonian.domain import Cancelled, Progress, Reporter, Source, checkpoint

EXCLUDED = {".git", ".venv", "node_modules", "__pycache__", ".DS_Store", ".env"}


def drive_id(url: str) -> str:
    parsed = urlparse(url.strip())
    match = re.fullmatch(r"/drive/(?:u/\d+/)?folders/([A-Za-z0-9_-]+)/?", parsed.path)
    if parsed.scheme != "https" or parsed.hostname != "drive.google.com" or not match:
        raise ValueError("Вставьте HTTPS-ссылку вида https://drive.google.com/drive/folders/…")
    return match.group(1)


def local_sources(folder: str, cancel: Event) -> list[Source]:
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("Локальная папка не найдена.")
    sources = []

    def failed(error: OSError) -> None:
        name = str(Path(error.filename or root).relative_to(root))
        sources.append(Source("", name, None, error="Нет доступа к папке: " + str(error)))

    for current, directories, files in os.walk(root, onerror=failed, followlinks=False):
        checkpoint(cancel)
        directories[:] = sorted(d for d in directories if d not in EXCLUDED)
        for name in sorted(files):
            if name in EXCLUDED or name.startswith(".env."):
                continue
            path = Path(current) / name
            relative = str(path.relative_to(root))
            if path.is_symlink():
                sources.append(Source("", relative, None, error="Символическая ссылка не обрабатывается."))
            else:
                sources.append(Source("", relative, path))
    for index, source in enumerate(sources, 1):
        source.id = f"F{index}"
    return sources


def drive_sources(url: str, destination: Path, emit: Reporter, cancel: Event) -> list[Source]:
    checkpoint(cancel)
    emit(Progress("Поиск", "Получаем список файлов Google Drive…"))
    files = gdown.download_folder(
        id=drive_id(url),
        output=str(destination),
        skip_download=True,
        quiet=True,
        use_cookies=False,
        timeout=(15, 45),
    )
    sources = []
    for index, item in enumerate(files, 1):
        if isinstance(item, str):
            raise ValueError("Google Drive вернул неожиданный формат списка файлов.")
        source = Source(f"F{index}", item.path, None, f"https://drive.google.com/file/d/{item.id}/view")
        sources.append(source)
    for index, (item, source) in enumerate(zip(files, sources, strict=True), 1):
        checkpoint(cancel)
        emit(Progress("Скачивание", source.name, index - 1, len(sources), source.id, "Скачивание"))
        try:
            target = destination / source.id
            target.mkdir(parents=True, exist_ok=True)

            def progress(done: int, total: int | None, name: str = source.name, current: int = index) -> None:
                checkpoint(cancel)
                amount = f"{done / 1024 / 1024:.1f} МБ"
                if total:
                    amount += f" / {total / 1024 / 1024:.1f} МБ"
                emit(Progress("Скачивание", f"{name} · {amount}", current - 1, len(sources)))

            result = gdown.download(
                id=item.id,
                output=str(target) + os.sep,
                quiet=True,
                use_cookies=False,
                timeout=(15, 45),
                retries=2,
                cancel=cancel,
                progress=progress,
            )
            checkpoint(cancel)
            if not isinstance(result, str) or not Path(result).is_file():
                raise ValueError("Google Drive не вернул файл.")
            source.path = Path(result)
        except Cancelled:
            raise
        except Exception as error:
            checkpoint(cancel)
            source.error = f"Не удалось скачать: {error}"
            source.status = "Не прочитан"
            emit(Progress("Скачивание", source.error, index, len(sources), source.id, source.status))
    return sources
