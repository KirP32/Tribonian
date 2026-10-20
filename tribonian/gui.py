import sys
from pathlib import Path
from threading import Event

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from tribonian.config import EXAMPLE_DRIVE, load_settings
from tribonian.domain import Cancelled, Progress, Report
from tribonian.llm import OpenRouter
from tribonian.pipeline import analyze, render_report, save_report

STYLE = """
QMainWindow { background: #f2f4f9; }
QWidget { font-family: "Inter", "Segoe UI", "Arial"; color: #26334a; font-size: 13px; }
QFrame#card { background: white; border: 1px solid #e2e6ee; border-radius: 16px; }
QLabel#title { font-size: 27px; font-weight: 700; color: #17243b; }
QLabel#subtitle, QLabel#muted { color: #728097; }
QLabel#section { font-size: 16px; font-weight: 600; }
QLabel#eyebrow { color: #7160d5; font-size: 11px; font-weight: 700; }
QLabel#brand { background: #6c58d9; color: white; border-radius: 12px;
    font-size: 25px; font-weight: 700; padding: 7px; }
QLabel#badge { background: #ece9fc; color: #6351c9; padding: 7px 12px; border-radius: 12px; }
QLineEdit, QComboBox { background: #f8f9fc; border: 1px solid #dce1eb;
    border-radius: 8px; padding: 8px; min-height: 18px; selection-background-color: #d9d2fb; }
QLineEdit:focus, QComboBox:focus { border-color: #8a77e4; }
QPushButton { background: #f7f8fb; border: 1px solid #dfe4ed; border-radius: 8px;
    padding: 7px 12px; min-height: 18px; font-weight: 500; }
QPushButton:hover { background: #eeebfb; border-color: #b6a8ed; }
QPushButton:disabled { color: #a3aabb; background: #f4f5f8; }
QPushButton#primary { background: #6c58d9; color: white; border: 0;
    padding: 12px; font-weight: 600; }
QPushButton#primary:hover { background: #5b46c4; }
QPushButton#primary:disabled { background: #b9b0e5; }
QPushButton#stop { color: #a24454; }
QProgressBar { border: none; border-radius: 4px; background: #eceef5;
    height: 7px; text-align: center; }
QProgressBar::chunk { border-radius: 4px; background: #8a77e4; }
QTableWidget { background: white; border: none; gridline-color: #f0f2f7;
    selection-background-color: #eeebfc; selection-color: #26334a; }
QHeaderView::section { background: #f7f8fb; color: #7a879c; border: none;
    padding: 8px; text-align: left; font-size: 11px; }
QTextBrowser { background: white; border: none; padding: 14px; font-size: 14px; }
QPlainTextEdit { background: #f7f8fb; border: 1px solid #e2e6ee; border-radius: 8px;
    font-family: "SF Mono", "Consolas", monospace; font-size: 11px; padding: 5px; }
QSplitter::handle { background: transparent; width: 18px; }
QScrollArea { border: none; background: transparent; }
QToolTip { background: #26334a; color: white; border: none; padding: 8px; }
"""


def label(text: str, kind: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    widget.setObjectName(kind)
    widget.setWordWrap(wrap)
    return widget


def card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(22, 22, 22, 22)
    layout.setSpacing(14)
    return frame, layout


class Worker(QThread):
    progress = Signal(object)
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, value: str, drive: bool, key: str, model: str, check: bool = False):
        super().__init__()
        self.value = value
        self.drive = drive
        self.key = key
        self.model = model
        self.check = check
        self.cancel = Event()

    def run(self) -> None:
        try:
            if self.check:
                api = OpenRouter(self.key, self.model, self.cancel, self.progress.emit)
                try:
                    answer = api.complete("Ответь одним словом: готов.", max_tokens=256)
                    self.result.emit(f"API работает · ответ: {answer} · стоимость ${api.cost:.6f}")
                finally:
                    api.close()
            else:
                self.result.emit(
                    analyze(
                        self.value,
                        self.drive,
                        self.key,
                        self.model,
                        self.progress.emit,
                        self.cancel,
                    )
                )
        except Cancelled:
            self.failed.emit("Обработка отменена. Можно начать заново.")
        except Exception as error:
            self.failed.emit(str(error).replace(self.key, "***") if self.key else str(error))


class Window(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.worker: Worker | None = None
        self.report: Report | None = None
        self.rows: dict[str, int] = {}
        self.closing = False
        self.setWindowTitle("Tribonian — Summary папки")
        self.resize(1240, 900)
        self.setMinimumSize(1000, 740)
        self.setStyleSheet(STYLE)
        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(30, 26, 30, 24)
        main.setSpacing(22)
        header = QHBoxLayout()
        logo = label("T", "brand")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFixedSize(48, 48)
        header.addWidget(logo)
        heading = QVBoxLayout()
        heading.setSpacing(3)
        heading.addWidget(label("Tribonian", "title"))
        heading.addWidget(label("Вся папка. Одна ясная картина.", "subtitle"))
        header.addLayout(heading)
        header.addStretch()
        header.addWidget(label("ТЕКСТ + ИЗОБРАЖЕНИЯ", "badge"))
        main.addLayout(header)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setHandleWidth(18)
        main.addWidget(split, 1)
        left = QWidget()
        left.setMinimumWidth(360)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(16)
        source_card, form = card()
        form.setSpacing(9)
        form.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        form.addWidget(label("01 / ИСТОЧНИК", "eyebrow"))
        form.addWidget(label("Добавьте папку", "section"))
        self.mode = QComboBox()
        self.mode.setAccessibleName("Источник документов")
        self.mode.addItems(["Google Drive", "Локальная папка"])
        form.addWidget(self.mode)
        self.source_pages = QStackedWidget()
        self.source_pages.setFixedHeight(38)
        self.drive_url = QLineEdit(EXAMPLE_DRIVE)
        self.drive_url.setCursorPosition(0)
        self.drive_url.setAccessibleName("Ссылка на папку Google Drive")
        self.drive_url.setPlaceholderText("https://drive.google.com/drive/folders/…")
        self.source_pages.addWidget(self.drive_url)
        local = QWidget()
        local_layout = QHBoxLayout(local)
        local_layout.setContentsMargins(0, 0, 0, 0)
        self.folder = QLineEdit()
        self.folder.setAccessibleName("Локальная папка")
        self.folder.setPlaceholderText("Путь к папке")
        browse = QPushButton("Выбрать")
        browse.clicked.connect(self.choose_folder)
        local_layout.addWidget(self.folder, 1)
        local_layout.addWidget(browse)
        self.source_pages.addWidget(local)
        self.mode.currentIndexChanged.connect(self.source_pages.setCurrentIndex)
        form.addWidget(self.source_pages)
        form.addWidget(
            label(
                "PDF, Word, Excel, PowerPoint, текст и изображения. Вложенные папки включены.",
                "muted",
                True,
            )
        )
        form.addWidget(label("02 / МОДЕЛЬ", "eyebrow"))
        key, model = load_settings()
        self.model = QLineEdit(model)
        self.model.setAccessibleName("Модель OpenRouter")
        form.addWidget(self.model)
        self.key = QLineEdit(key)
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Ключ OpenRouter · sk-or-v1-…")
        self.key.setAccessibleName("Ключ OpenRouter")
        form.addWidget(self.key)
        key_row = QHBoxLayout()
        self.check_button = QPushButton("Проверить ключ")
        self.check_button.clicked.connect(lambda: self.start(True))
        key_row.addWidget(self.check_button)
        key_row.addStretch()
        self.show_key = QPushButton("Показать")
        self.show_key.setCheckable(True)
        self.show_key.toggled.connect(self.toggle_key)
        key_row.addWidget(self.show_key)
        form.addLayout(key_row)
        self.start_button = QPushButton("Создать Summary  →")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(lambda: self.start(False))
        form.addWidget(self.start_button)
        form.addWidget(
            label(
                "Содержимое выбранной папки отправляется в OpenRouter для анализа.",
                "muted",
                True,
            )
        )
        left_layout.addWidget(source_card)
        progress_card, progress_layout = card()
        progress_layout.setSpacing(10)
        progress_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        progress_layout.addWidget(label("03 / ОБРАБОТКА", "eyebrow"))
        status_row = QHBoxLayout()
        self.phase = label("Готов к работе", "section")
        status_row.addWidget(self.phase, 1)
        self.stop = QPushButton("Отмена")
        self.stop.setObjectName("stop")
        self.stop.setEnabled(False)
        self.stop.clicked.connect(self.cancel)
        status_row.addWidget(self.stop)
        progress_layout.addLayout(status_row)
        self.detail = label("Выберите источник и запустите анализ.", "muted", True)
        self.detail.setMinimumHeight(35)
        progress_layout.addWidget(self.detail)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(7)
        progress_layout.addWidget(self.progress)
        self.counter = label("Файлы появятся здесь после запуска", "muted")
        progress_layout.addWidget(self.counter)
        self.files = QTableWidget(0, 2)
        self.files.setHorizontalHeaderLabels(["ФАЙЛ", "СТАТУС"])
        self.files.verticalHeader().hide()
        self.files.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.files.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.files.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.files.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.files.setMinimumHeight(100)
        progress_layout.addWidget(self.files, 1)
        left_layout.addWidget(progress_card, 1)
        sidebar = QScrollArea()
        sidebar.setWidgetResizable(True)
        sidebar.setWidget(left)
        sidebar.setMinimumWidth(385)
        split.addWidget(sidebar)
        result_card, result_layout = card()
        result_header = QHBoxLayout()
        result_heading = QVBoxLayout()
        result_heading.addWidget(label("РЕЗУЛЬТАТ", "eyebrow"))
        result_heading.addWidget(label("Summary", "title"))
        result_header.addLayout(result_heading)
        result_header.addStretch()
        self.copy = QPushButton("Копировать")
        self.copy.setEnabled(False)
        self.copy.clicked.connect(self.copy_summary)
        self.save = QPushButton("Сохранить")
        self.save.setEnabled(False)
        self.save.clicked.connect(self.save_summary)
        result_header.addWidget(self.copy)
        result_header.addWidget(self.save)
        result_layout.addLayout(result_header)
        self.coverage = label("Главное, связи между документами и пробелы в данных.", "muted", True)
        result_layout.addWidget(self.coverage)
        self.result_pages = QStackedWidget()
        welcome = QWidget()
        welcome_layout = QVBoxLayout(welcome)
        welcome_layout.addStretch()
        icon = label("≋", "title")
        icon.setStyleSheet("font-size: 70px; color: #a99ae7;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addWidget(icon)
        empty_title = label("От документов к общей картине", "section")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addWidget(empty_title)
        empty_text = label(
            "Приложение прочитает файлы, проанализирует изображения\n"
            "и соберёт общий Summary со ссылками на источники.\n\n"
            "Непрочитанные файлы и предположения будут отмечены отдельно.",
            "muted",
            True,
        )
        empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addWidget(empty_text)
        welcome_layout.addStretch()
        self.result_pages.addWidget(welcome)
        self.summary = QTextBrowser()
        self.summary.setAccessibleName("Общий Summary")
        self.summary.setOpenExternalLinks(False)
        self.summary.setOpenLinks(False)
        self.summary.document().setDefaultStyleSheet(
            "h1 {color:#17243b; font-size:24px;} h2 {color:#514494; margin-top:22px;}"
            "p, li {line-height:1.55;} table {border-collapse:collapse;}"
            "td, th {padding:7px; border:1px solid #e2e6ee;}"
        )
        self.result_pages.addWidget(self.summary)
        result_layout.addWidget(self.result_pages, 1)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.log.setMaximumHeight(95)
        self.log.setPlaceholderText("Здесь будет журнал чтения и запросов к модели.")
        result_layout.addWidget(self.log)
        split.addWidget(result_card)
        split.setSizes([400, 780])
        self.statusBar().showMessage("MiniMax M3.1 Flash · OpenRouter")

    def toggle_key(self, checked: bool) -> None:
        self.key.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password)
        self.show_key.setText("Скрыть" if checked else "Показать")

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку с документами")
        if folder:
            self.folder.setText(folder)

    def start(self, check: bool = False) -> None:
        if self.worker:
            return
        drive = self.mode.currentIndex() == 0
        value = self.drive_url.text().strip() if drive else self.folder.text().strip()
        if not self.key.text().strip() or not self.model.text().strip():
            self.show_error("Укажите ключ и модель OpenRouter.")
            return
        if not check and not value:
            self.show_error("Выберите локальную папку или вставьте ссылку Google Drive.")
            return
        if not check:
            self.report = None
            self.rows.clear()
            self.files.setRowCount(0)
            self.log.clear()
            self.copy.setEnabled(False)
            self.save.setEnabled(False)
            self.result_pages.setCurrentIndex(0)
            self.coverage.setText("Обрабатываем файлы. Результат появится после завершения.")
        self.start_button.setEnabled(False)
        self.check_button.setEnabled(False)
        self.stop.setEnabled(True)
        self.phase.setText("Проверка API" if check else "Запуск")
        self.detail.setText("Ожидаем ответ…" if check else "Получаем содержимое папки…")
        self.progress.setRange(0, 0)
        self.worker = Worker(value, drive, self.key.text().strip(), self.model.text().strip(), check)
        self.worker.progress.connect(self.on_progress)
        self.worker.result.connect(self.on_result)
        self.worker.failed.connect(self.show_error)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def cancel(self) -> None:
        if self.worker:
            self.worker.cancel.set()
            self.stop.setEnabled(False)
            self.detail.setText("Отмена… ожидаем завершения текущего сетевого запроса.")

    def on_progress(self, progress: Progress) -> None:
        self.phase.setText(progress.phase)
        self.detail.setText(progress.message[:160])
        self.detail.setToolTip(progress.message)
        if progress.total:
            self.progress.setRange(0, progress.total)
            self.progress.setValue(progress.done)
            self.counter.setText(f"{progress.phase}: {progress.done} / {progress.total}")
        else:
            self.progress.setRange(0, 0)
        self.log.appendPlainText(f"{progress.phase} · {progress.message}")
        if progress.file_id:
            row = self.rows.get(progress.file_id)
            if row is None:
                row = self.files.rowCount()
                self.rows[progress.file_id] = row
                self.files.insertRow(row)
                self.files.setItem(row, 0, QTableWidgetItem(f"[{progress.file_id}] {progress.message}"))
            if progress.status:
                self.files.setItem(row, 1, QTableWidgetItem(progress.status))

    def on_result(self, result: object) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        if isinstance(result, str):
            self.phase.setText("Ключ работает")
            self.detail.setText(result)
            self.log.appendPlainText(result)
        elif isinstance(result, Report):
            self.report = result
            self.summary.setMarkdown(render_report(result))
            self.result_pages.setCurrentIndex(1)
            self.copy.setEnabled(True)
            self.save.setEnabled(True)
            full = sum(source.status == "Прочитан" for source in result.sources)
            partial = sum(source.status == "Частично" for source in result.sources)
            failed = len(result.sources) - full - partial
            self.phase.setText(
                "Готово" if full == len(result.sources) and not result.warning else "Есть пробелы"
            )
            self.coverage.setText(f"Прочитано: {full} · Частично: {partial} · Не прочитано: {failed}")
            self.detail.setText(
                result.warning or f"Проанализировано {full + partial} из {len(result.sources)} файлов."
            )
            self.counter.setText(
                f"Запросов: {result.requests} · Токенов: {result.tokens:,} · ${result.cost:.6f}"
            )
            for source in result.sources:
                row = self.rows.get(source.id)
                if row is not None:
                    item = QTableWidgetItem(f"[{source.id}] {source.name}")
                    item.setToolTip(source.name + ("\n" + source.error if source.error else ""))
                    self.files.setItem(row, 0, item)
                    status = QTableWidgetItem(source.status)
                    status.setToolTip(source.error or f"Обработано частей: {source.completed}/{source.units}")
                    status.setForeground(QColor("#24816c" if source.status == "Прочитан" else "#b66b31"))
                    self.files.setItem(row, 1, status)

    def show_error(self, message: str) -> None:
        self.phase.setText("Обработка остановлена")
        self.detail.setText(message)
        self.detail.setToolTip(message)
        self.log.appendPlainText(message)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        if self.report is None:
            self.coverage.setText("Обработка не завершена: " + message)

    def on_finished(self) -> None:
        if self.worker:
            self.worker.deleteLater()
            self.worker = None
        self.start_button.setEnabled(True)
        self.check_button.setEnabled(True)
        self.stop.setEnabled(False)
        if self.closing:
            self.close()

    def copy_summary(self) -> None:
        if self.report:
            QApplication.clipboard().setText(render_report(self.report))
            self.statusBar().showMessage("Summary скопирован", 4000)

    def save_summary(self) -> None:
        if not self.report:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить Summary", "summary.md", "Markdown (*.md);;JSON (*.json)"
        )
        if path:
            try:
                save_report(self.report, Path(path))
                self.statusBar().showMessage(f"Сохранено: {path}", 6000)
            except OSError as error:
                QMessageBox.warning(self, "Не удалось сохранить", str(error))

    def closeEvent(self, event) -> None:
        if self.worker:
            self.closing = True
            self.cancel()
            event.ignore()
        else:
            event.accept()


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Tribonian")
    app.setFont(QFont("Arial", 12))
    window = Window()
    window.show()
    sys.exit(app.exec())
