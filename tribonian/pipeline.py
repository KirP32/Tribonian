import json
import tempfile
from pathlib import Path
from threading import Event

from tribonian.domain import ApiError, Cancelled, Progress, Report, Reporter, Source, Unit, checkpoint
from tribonian.extract import chunks, extract_units
from tribonian.llm import OpenRouter
from tribonian.sources import drive_sources, local_sources

MAP_PROMPT = """Проанализируй фрагмент источника [{id}] {name}.
Расположение: {label}.
Составь содержательную выжимку: тема, существенные факты, числа, даты, выводы,
ограничения. Для правовых документов сохрани ключевые правила и исключения.
Описывай предоставленную редакцию; её актуальность не проверялась.
Не называй текст закона комментарием без явных признаков комментария.
Для изображения прочитай доступный текст, опиши смысл, схему и важные детали.
Не угадывай неразборчивый текст. В каждом тематическом пункте укажи [{id}]
и при наличии страницу. Это часть материала: не делай вывод о всей папке.
Верни только JSON-объект с полями:
status: "read", "partial" или "unread";
summary: строка с содержательной выжимкой;
limitations: строка с конкретной причиной неполного прочтения, иначе пустая.
"read" означает, что всё значимое предоставленное содержимое читается.
"partial" означает, что часть предоставленных данных неразборчива.
"unread" означает, что содержательно прочитать фрагмент не удалось.
Сам по себе отрывок документа не означает "partial": оценивай читаемость
переданных данных, а не наличие всего кодекса или книги.

ДАННЫЕ:
{text}"""

FINAL_PROMPT = """Составь общий Summary всей папки на русском.
Объедини информацию по темам, покажи связи и противоречия между документами,
не ограничивайся пересказом каждого файла. Не выдумывай общую тему,
если источники разнородны. Сохрани важные числа, даты и ограничения.
Используй Markdown и заголовки:
## Главное
## Содержание и взаимосвязи
## Важные детали и противоречия
## Что осталось неизвестным
## Предположения о непрочитанных файлах
Факты сопровождай идентификаторами [F1], [F2].
Для частично прочитанных источников явно укажи границы доступного.
Фрагменты могут продолжать друг друга: сопоставь все части перед выводом,
что какой-либо текст отсутствует. Фрагмент кодекса может составлять весь
предоставленный файл; не смешивай неполный кодекс и неполное чтение файла.
Для непрочитанных файлов предложи осторожную догадку по имени и общему
контексту. Каждый такой пункт начни «Предположение, содержимое не проверено».
Если имя неинформативно, скажи, что предположение невозможно.
Не приписывай предположениям уверенность факта. Если непрочитанных нет,
так и напиши. Пиши содержательно и без повторов.

РЕЕСТР ИСТОЧНИКОВ:
{manifest}

ИЗВЛЕЧЁННОЕ СОДЕРЖАНИЕ:
{notes}"""


def safe_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def source_manifest(sources: list[Source]) -> str:
    return json.dumps(
        [
            {
                "id": source.id,
                "file": source.name,
                "status": source.status,
                "analyzed_parts": source.completed,
                "extracted_parts": source.units,
                "problem": source.error,
            }
            for source in sources
        ],
        ensure_ascii=False,
    )


def parse_analysis(response: str) -> tuple[str, str, str]:
    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        raise ApiError("Модель вернула невалидный JSON анализа.") from None
    if not isinstance(data, dict):
        raise ApiError("Модель вернула неверную структуру анализа.")
    status = data.get("status")
    summary = data.get("summary")
    limitations = data.get("limitations")
    if (
        status not in ("read", "partial", "unread")
        or not isinstance(summary, str)
        or not isinstance(limitations, str)
        or (status != "unread" and not summary.strip())
    ):
        raise ApiError("Модель не подтвердила читаемость фрагмента в ожидаемом формате.")
    return status, summary.strip(), limitations.strip()


def verification_context(prepared: list[tuple[Source, list[Unit]]]) -> tuple[str, list[str]]:
    text = []
    images = []
    for source, units in prepared:
        if source.status != "Прочитан":
            continue
        for unit in units:
            text.append(f"[{source.id}] {unit.label}\n{unit.text}")
            for image in unit.images:
                images.append(image)
                text.append(f"Приложенное изображение №{len(images)}: [{source.id}] {unit.label}")
    evidence = "\n\n".join(text)
    if len(evidence) > 80000 or len(images) > 8 or sum(map(len, images)) > 12000000:
        return "", []
    return (
        "\n\nПЕРВИЧНЫЕ ДАННЫЕ ДЛЯ СВЕРКИ:\n"
        "Сверь выжимки с данными ниже и приложенными изображениями. "
        "Первичные данные имеют приоритет. Сомнительные слова не угадывай. "
        "Не добавляй интерпретации, которых нет в источниках.\n" + evidence,
        images,
    )


def render_report(report: Report) -> str:
    rows = [
        "# Summary",
        "",
        report.summary,
        "",
        "## Покрытие файлов",
        "",
        "| Источник | Файл | Статус | Части LLM | Проблема |",
        "|---|---|---|---|---|",
    ]
    for source in report.sources:
        rows.append(
            f"| [{source.id}] | {safe_cell(source.name)} | {source.status} | "
            f"{source.completed}/{source.units} | {safe_cell(source.error) or '—'} |"
        )
    rows.extend(
        [
            "",
            f"Запросов: {report.requests}. Токенов: {report.tokens:,}. Стоимость по API: ${report.cost:.6f}.",
        ]
    )
    if report.warning:
        rows.extend(["", "**Ограничение:** " + report.warning])
    rows.extend(["", "## Источники", ""])
    for source in report.sources:
        rows.append(f"- [{source.id}] {source.name}" + (f" — {source.origin}" if source.origin else ""))
    return "\n".join(rows) + "\n"


def save_report(report: Report, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        data = {
            "summary": report.summary,
            "model": report.model,
            "requests": report.requests,
            "tokens": report.tokens,
            "cost": report.cost,
            "warning": report.warning,
            "sources": [
                {
                    "id": s.id,
                    "name": s.name,
                    "origin": s.origin,
                    "status": s.status,
                    "error": s.error,
                    "units": s.units,
                    "completed": s.completed,
                    "notes": s.notes,
                }
                for s in report.sources
            ],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        path.write_text(render_report(report), encoding="utf-8")


def analyze(
    value: str,
    drive: bool,
    key: str,
    model: str,
    emit: Reporter,
    cancel: Event,
    client: OpenRouter | None = None,
) -> Report:
    api = client or OpenRouter(key, model, cancel, emit)
    try:
        with tempfile.TemporaryDirectory(prefix="tribonian-") as temporary:
            emit(Progress("Поиск", "Ищем документы…"))
            sources = (
                drive_sources(value, Path(temporary), emit, cancel) if drive else local_sources(value, cancel)
            )
            if not sources:
                raise ValueError("В папке нет доступных файлов.")
            prepared = []
            for index, source in enumerate(sources, 1):
                checkpoint(cancel)
                emit(Progress("Чтение", source.name, index - 1, len(sources), source.id, "Чтение"))
                units = []
                if source.path:
                    try:
                        for unit in extract_units(source.path, cancel):
                            units.append(unit)
                            emit(
                                Progress(
                                    "Чтение",
                                    f"{source.name} · {unit.label}",
                                    index - 1,
                                    len(sources),
                                    source.id,
                                    "Чтение",
                                )
                            )
                        if not units:
                            source.error = "Файл пуст или извлекаемое содержимое отсутствует."
                    except Cancelled:
                        raise
                    except Exception as error:
                        source.error = f"Ошибка чтения: {error}"
                source.units = len(units)
                source.status = "Извлечён" if units else "Не прочитан"
                prepared.append((source, units))
                emit(Progress("Чтение", source.name, index, len(sources), source.id, source.status))
            total = sum(len(units) for _, units in prepared)
            done = 0
            for source, units in prepared:
                for unit in units:
                    checkpoint(cancel)
                    emit(
                        Progress(
                            "Анализ LLM",
                            f"{source.name} · {unit.label}",
                            done,
                            total,
                            source.id,
                            f"LLM {source.completed}/{source.units}",
                        )
                    )
                    try:
                        response = api.complete(
                            MAP_PROMPT.format(
                                id=source.id,
                                name=source.name,
                                label=unit.label,
                                text=unit.text,
                            ),
                            unit.images,
                            json_mode=True,
                        )
                        reading_status, note, limitation = parse_analysis(response)
                        if reading_status != "read":
                            reason = limitation or "Модель не смогла полностью прочитать фрагмент."
                            source.error = "; ".join(filter(None, [source.error, f"{unit.label}: {reason}"]))
                        if reading_status != "unread":
                            source.notes.append(f"[{source.id}] {unit.label}\n{note}")
                            source.completed += 1
                    except ApiError as error:
                        source.error = "; ".join(filter(None, [source.error, f"{unit.label}: {error}"]))
                        emit(
                            Progress(
                                "Ошибка LLM", f"{source.name}: {error}", done, total, source.id, "Ошибка LLM"
                            )
                        )
                    done += 1
                    emit(Progress("Анализ LLM", source.name, done, total, source.id))
                source.status = (
                    "Прочитан"
                    if source.completed and source.completed == source.units and not source.error
                    else "Частично"
                    if source.completed
                    else "Не прочитан"
                )
                emit(Progress("Анализ LLM", source.name, done, total, source.id, source.status))
            checkpoint(cancel)
            emit(Progress("Общий Summary", "Объединяем факты и отмечаем пробелы…"))
            notes = "\n\n".join(note for source in sources for note in source.notes)
            warning = ""
            try:
                while len(notes) > 120000:
                    reduced = []
                    for index, group in enumerate(chunks(notes, 70000), 1):
                        checkpoint(cancel)
                        emit(Progress("Общий Summary", f"Объединяем группу {index}…"))
                        reduced.append(
                            api.complete(
                                "Сожми записи без потери основных тем, чисел, противоречий и ссылок [F…]. "
                                "Сохрани вклад каждого упомянутого источника.\n\n" + group,
                            )
                        )
                    compact = "\n\n".join(reduced)
                    if len(compact) >= len(notes):
                        raise ApiError("Не удалось уменьшить объём промежуточных результатов.")
                    notes = compact
                evidence, images = verification_context(prepared)
                summary = api.complete(
                    FINAL_PROMPT.format(
                        manifest=source_manifest(sources), notes=notes or "Нет прочитанных данных."
                    )
                    + evidence,
                    images=images,
                )
            except ApiError as error:
                warning = f"Общий Summary не сформирован: {error}"
                summary = (
                    "## Общий Summary недоступен\n\n"
                    + warning
                    + "\n\n## Сохранённые результаты по фрагментам\n\n"
                    + (notes or "Ни один фрагмент не удалось проанализировать.")
                    + "\n\n## Предположения о непрочитанных файлах\n\n"
                    "Модель недоступна; предположения не сформированы."
                )
            report = Report(summary, sources, model, api.requests, api.tokens, api.cost, warning)
            emit(Progress("Готово", "Отчёт готов", 1, 1))
            return report
    finally:
        if client is None:
            api.close()
