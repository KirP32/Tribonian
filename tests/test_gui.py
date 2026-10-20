import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit

from tribonian.domain import Progress, Report, Source
from tribonian.gui import Window


def test_ui_source_switch_result_copy_and_failure_status(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    app = QApplication.instance() or QApplication([])
    window = Window()
    window.show()
    app.processEvents()
    labels = [item.text() for item in window.findChildren(QLabel)]
    assert "Суммарный итог по папке" in labels
    assert "Вся папка. Одна ясная картина." not in labels
    assert "ТЕКСТ + ИЗОБРАЖЕНИЯ" not in labels
    assert not any("отправляется в OpenRouter" in text for text in labels)
    assert not any(field.accessibleName() == "Модель OpenRouter" for field in window.findChildren(QLineEdit))
    window.mode.setCurrentIndex(1)
    assert window.folder.isVisible()
    assert not window.drive_url.isVisible()
    assert window.key.echoMode() == window.key.EchoMode.Password
    window.on_progress(Progress("Чтение", "budget.xls", 0, 1, "F1", "Чтение"))
    source = Source("F1", "budget.xls", None, status="Не прочитан", error="Формат не поддерживается")
    report = Report(
        "# Summary\n\nПредположение, содержимое не проверено: бюджет [F1].", [source], "model", 1, 100, 0
    )
    window.on_result(report)
    assert "Не прочитано: 1" in window.coverage.text()
    assert window.files.item(0, 1).text() == "Не прочитан"
    assert "Предположение" in window.summary.toPlainText()
    assert "Summary" not in window.summary.toPlainText()
    assert "[F1]" not in window.summary.toPlainText()
    assert window.files.item(0, 0).text() == "budget.xls"
    QTest.mouseClick(window.copy, Qt.MouseButton.LeftButton)
    assert "Покрытие файлов" in QApplication.clipboard().text()
    assert QApplication.clipboard().text().count("# Summary") == 1
    assert "[F1]" not in QApplication.clipboard().text()
    assert window.start_button.height() >= 35
    window.close()
