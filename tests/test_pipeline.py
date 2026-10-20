import json
from threading import Event

import pytest

from tribonian.domain import ApiError, Cancelled, Source, Unit
from tribonian.pipeline import analyze, parse_analysis, render_report, save_report, verification_context
from tribonian.sources import drive_id, local_sources


class FakeModel:
    def __init__(self, fail_map=False, fail_summary=False):
        self.prompts = []
        self.requests = 0
        self.tokens = 0
        self.cost = 0
        self.fail_map = fail_map
        self.fail_summary = fail_summary

    def complete(self, prompt, images=None, json_mode=False):
        self.prompts.append(prompt)
        self.requests += 1
        if self.fail_map and prompt.startswith("Проанализируй"):
            raise ApiError("HTTP 429: лимит")
        if self.fail_summary and prompt.startswith("Составь общий"):
            raise ApiError("HTTP 503: сервис недоступен")
        if json_mode:
            return json.dumps({"status": "read", "summary": "Проверенные факты [F1].", "limitations": ""})
        return "# Summary\n\n## Главное\nПроверенные факты [F1, стр. 9; F2, с. 1–2], [F2]."


def run(folder, client=None, emit=None):
    return analyze(
        str(folder), False, "test-key", "test-model", emit or (lambda p: None), Event(), client or FakeModel()
    )


def test_nested_files_and_empty_file_are_accounted_for(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "contract.txt").write_text("Договор действует 12 месяцев.", encoding="utf-8")
    (tmp_path / "empty.txt").touch()
    (tmp_path / ".env").write_text("SECRET=private", encoding="utf-8")
    report = run(tmp_path)
    assert len(report.sources) == 2
    assert {s.status for s in report.sources} == {"Прочитан", "Не прочитан"}
    empty = next(s for s in report.sources if s.name == "empty.txt")
    assert "пуст" in empty.error


def test_unread_file_is_in_final_prompt_with_inference_label(tmp_path):
    (tmp_path / "brief.txt").write_text("Открываем офис в Москве.", encoding="utf-8")
    (tmp_path / "office_budget.xls").write_bytes(b"unknown legacy spreadsheet")
    model = FakeModel()
    report = run(tmp_path, model)
    assert report.sources[1].status == "Не прочитан"
    assert "office_budget.xls" in model.prompts[-1]
    assert "Предположение, содержимое не проверено" in model.prompts[-1]
    assert "формат" in report.sources[1].error.lower()


def test_partial_extraction_preserves_readable_parts(tmp_path, monkeypatch):
    (tmp_path / "damaged.pdf").touch()

    def damaged(path, cancel):
        yield Unit("Страница 1", "Сохранённый текст")
        raise ValueError("Страница 2 повреждена")

    monkeypatch.setattr("tribonian.pipeline.extract_units", damaged)
    report = run(tmp_path)
    assert report.sources[0].status == "Частично"
    assert report.sources[0].completed == 1
    assert "Страница 2 повреждена" in report.sources[0].error


def test_model_failure_does_not_mark_file_read(tmp_path):
    (tmp_path / "brief.txt").write_text("Текст", encoding="utf-8")
    report = run(tmp_path, FakeModel(fail_map=True))
    assert report.sources[0].status == "Не прочитан"
    assert report.sources[0].completed == 0
    assert "429" in report.sources[0].error


def test_summary_failure_keeps_per_fragment_results(tmp_path):
    (tmp_path / "brief.txt").write_text("Текст", encoding="utf-8")
    report = run(tmp_path, FakeModel(fail_summary=True))
    assert "503" in report.warning
    assert "Проверенные факты" in report.summary
    assert report.sources[0].status == "Прочитан"


def test_all_unread_still_produce_explicit_inference_request(tmp_path):
    (tmp_path / "unknown.zip").write_bytes(b"bad archive")
    model = FakeModel()
    report = run(tmp_path, model)
    assert len(model.prompts) == 1
    assert "Нет прочитанных данных" in model.prompts[0]
    assert report.sources[0].status == "Не прочитан"


def test_markdown_and_json_exports_include_coverage(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    (folder / "brief.txt").write_text("План", encoding="utf-8")
    report = run(folder)
    save_report(report, tmp_path / "summary.json")
    save_report(report, tmp_path / "summary.md")
    data = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert data["sources"][0]["status"] == "Прочитан"
    assert data["summary"] == "## Главное\nПроверенные факты."
    markdown = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert markdown.count("# Summary") == 1
    assert "[F1]" not in markdown
    assert "[F2]" not in markdown
    assert "Покрытие файлов" in render_report(report)
    assert "test-key" not in (tmp_path / "summary.json").read_text(encoding="utf-8")


def test_empty_folder_reports_clear_error(tmp_path):
    with pytest.raises(ValueError, match="нет доступных файлов"):
        run(tmp_path)


def test_cancellation_stops_before_api(tmp_path):
    stop = Event()
    stop.set()
    model = FakeModel()
    with pytest.raises(Cancelled):
        analyze(str(tmp_path), False, "key", "model", lambda p: None, stop, model)
    assert model.requests == 0


@pytest.mark.parametrize(
    "url",
    [
        "http://drive.google.com/drive/folders/abc",
        "https://evil.example/drive/folders/abc",
        "https://drive.google.com/file/d/abc/view",
    ],
)
def test_drive_rejects_wrong_url(url):
    with pytest.raises(ValueError):
        drive_id(url)


def test_drive_url_with_query_is_supported():
    assert drive_id("https://drive.google.com/drive/folders/abc_123?usp=sharing") == "abc_123"


def test_missing_folder(tmp_path):
    with pytest.raises(ValueError, match="не найдена"):
        local_sources(str(tmp_path / "missing"), Event())


def test_long_file_last_fragment_reaches_model(tmp_path):
    (tmp_path / "long.txt").write_text(
        "Начало\n" + "Текст " * 30000 + "\nПоследний факт: 987654321.", encoding="utf-8"
    )
    model = FakeModel()
    report = run(tmp_path, model)
    assert report.sources[0].units >= 3
    assert any("987654321" in prompt for prompt in model.prompts[:-1])
    assert report.sources[0].status == "Прочитан"


def test_small_folder_final_verification_excludes_unread_sources():
    read = Source("F1", "read.txt", None, status="Прочитан")
    unread = Source("F2", "unread.txt", None, status="Не прочитан")
    text, images = verification_context(
        [
            (read, [Unit("Страница 1", "Проверяемый факт", ["data:image/jpeg;base64,ok"])]),
            (unread, [Unit("Страница 1", "Не подтверждено")]),
        ]
    )
    assert "Проверяемый факт" in text
    assert "Не подтверждено" not in text
    assert len(images) == 1


@pytest.mark.parametrize("status", ["partial", "unread"])
def test_model_reported_readability_controls_file_status(tmp_path, status):
    (tmp_path / "scan.txt").write_text("Неразборчивый фрагмент", encoding="utf-8")

    class ReadabilityModel(FakeModel):
        def complete(self, prompt, images=None, json_mode=False):
            if json_mode:
                return json.dumps(
                    {
                        "status": status,
                        "summary": "Доступная часть" if status == "partial" else "",
                        "limitations": "Мелкий текст не читается.",
                    }
                )
            return "Предположение, содержимое не проверено."

    report = run(tmp_path, ReadabilityModel())
    assert report.sources[0].status == ("Частично" if status == "partial" else "Не прочитан")
    assert "Мелкий текст" in report.sources[0].error


@pytest.mark.parametrize("response", ["[]", '{"status":"read"}', "not json"])
def test_invalid_analysis_is_not_accepted(response):
    with pytest.raises(ApiError):
        parse_analysis(response)


def test_large_folder_is_reduced_in_groups_before_final_summary(tmp_path):
    for number in range(3):
        (tmp_path / f"document-{number}.txt").write_text(f"Файл {number}", encoding="utf-8")

    class LargeModel(FakeModel):
        def complete(self, prompt, images=None, json_mode=False):
            if json_mode:
                self.prompts.append(prompt)
                self.requests += 1
                return json.dumps({"status": "read", "summary": "Факт. " * 9000, "limitations": ""})
            return super().complete(prompt, images)

    model = LargeModel()
    report = run(tmp_path, model)
    group_requests = [p for p in model.prompts if p.startswith("Сожми записи")]
    assert len(group_requests) >= 3
    assert model.prompts[-1].startswith("Составь общий")
    assert all(s.status == "Прочитан" for s in report.sources)
    assert not report.warning
