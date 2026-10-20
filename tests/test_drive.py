from pathlib import Path
from threading import Event
from types import SimpleNamespace

from tribonian.sources import drive_sources


def test_one_download_failure_does_not_hide_other_files(monkeypatch, tmp_path):
    items = [
        SimpleNamespace(id="one", path="same.txt"),
        SimpleNamespace(id="two", path="same.txt"),
        SimpleNamespace(id="three", path="broken.pdf"),
    ]
    monkeypatch.setattr("tribonian.sources.gdown.download_folder", lambda **kwargs: items)

    def download(**kwargs):
        if kwargs["id"] == "three":
            raise RuntimeError("Download forbidden")
        path = Path(kwargs["output"]) / "same.txt"
        path.write_text(kwargs["id"], encoding="utf-8")
        return str(path)

    monkeypatch.setattr("tribonian.sources.gdown.download", download)
    sources = drive_sources(
        "https://drive.google.com/drive/folders/public", tmp_path, lambda p: None, Event()
    )
    assert len(sources) == 3
    assert sources[0].path.read_text(encoding="utf-8") == "one"
    assert sources[1].path.read_text(encoding="utf-8") == "two"
    assert sources[2].status == "Не прочитан"
    assert "forbidden" in sources[2].error
