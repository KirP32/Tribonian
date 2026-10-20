from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event


class Cancelled(Exception):
    pass


class ApiError(Exception):
    pass


@dataclass
class Progress:
    phase: str
    message: str
    done: int = 0
    total: int = 0
    file_id: str = ""
    status: str = ""


Reporter = Callable[[Progress], None]


@dataclass
class Source:
    id: str
    name: str
    path: Path | None
    origin: str = ""
    status: str = "Ожидает"
    error: str = ""
    units: int = 0
    completed: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass
class Unit:
    label: str
    text: str = ""
    images: list[str] = field(default_factory=list)


@dataclass
class Report:
    summary: str
    sources: list[Source]
    model: str
    requests: int
    tokens: int
    cost: float
    warning: str = ""


def checkpoint(cancel: Event) -> None:
    if cancel.is_set():
        raise Cancelled("Обработка остановлена пользователем.")
