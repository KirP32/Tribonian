import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tribonian.domain import Progress, Report, Source
from tribonian.gui import Window


def test_ui_source_switch_result_copy_and_failure_status(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    app = QApplication.instance() or QApplication([])
    window = Window()
    window.show()
    app.processEvents()
    window.mode.setCurrentIndex(1)
    assert window.folder.isVisible()
    assert not window.drive_url.isVisible()
    assert window.key.echoMode() == window.key.EchoMode.Password
    window.on_progress(Progress("Чтение", "budget.xls", 0, 1, "F1", "Чтение"))
    source = Source("F1", "budget.xls", None, status="Не прочитан", error="Формат не поддерживается")
    report = Report("Предположение, содержимое не проверено: бюджет.", [source], "model", 1, 100, 0)
    window.on_result(report)
    assert "Не прочитано: 1" in window.coverage.text()
    assert window.files.item(0, 1).text() == "Не прочитан"
    assert "Предположение" in window.summary.toPlainText()
    QTest.mouseClick(window.copy, Qt.MouseButton.LeftButton)
    assert "Покрытие файлов" in QApplication.clipboard().text()
    assert window.start_button.height() >= 35
    window.close()
